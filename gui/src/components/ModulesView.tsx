import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useDraft } from "../lib/useDraft";
import { useStore } from "../store";
import type { ModuleSettings, SettingField } from "../types";
import { SaveBar } from "./SaveBar";

/**
 * The mask the backend substitutes for a stored secret. Sending it back
 * unchanged means "leave the stored value alone", which is exactly what
 * should happen when nobody typed in the field.
 */
const SECRET_MASK = "***";

/** Read a dotted path like "govee.api_key" out of a module's settings. */
function readPath(source: Record<string, unknown>, key: string): unknown {
  return key.split(".").reduce<unknown>((value, part) => {
    if (value && typeof value === "object") {
      return (value as Record<string, unknown>)[part];
    }
    return undefined;
  }, source);
}

/** Write a dotted path, creating the intermediate objects it needs. */
function writePath(
  source: Record<string, unknown>,
  key: string,
  value: unknown,
): Record<string, unknown> {
  const parts = key.split(".");
  const head = parts[0]!;
  if (parts.length === 1) return { ...source, [head]: value };
  const nested = (source[head] ?? {}) as Record<string, unknown>;
  return { ...source, [head]: writePath(nested, parts.slice(1).join("."), value) };
}

export function ModulesView() {
  const { t } = useTranslation();
  const settings = useStore((s) => s.settings);
  const schemas = useStore((s) => s.schemas);
  const saveSettings = useStore((s) => s.saveSettings);

  const { draft, dirty, state, edit, reset, save } = useDraft(
    settings ? settings.modules : null,
  );
  if (!draft) return null;

  const names = Object.keys(draft).sort();

  return (
    <div className="view">
      <div className="view-head">
        <h2>{t("modules.title")}</h2>
        <p>{t("modules.help")}</p>
      </div>

      {names.map((name) => (
        <ModuleCard
          key={name}
          name={name}
          settings={draft[name]!}
          schema={schemas[name] ?? []}
          onChange={(next) => edit((current) => ({ ...current, [name]: next }))}
        />
      ))}

      <SaveBar
        dirty={dirty}
        state={state}
        onReset={reset}
        onSave={() => void save((modules) => saveSettings({ modules }))}
      />
    </div>
  );
}

function ModuleCard({
  name,
  settings,
  schema,
  onChange,
}: {
  name: string;
  settings: ModuleSettings;
  schema: SettingField[];
  onChange: (next: ModuleSettings) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  // Modules label themselves through the dashboard's own translation file, so
  // a new module needs no entry here. Falling back to the bare name keeps an
  // untranslated module visible instead of blank.
  const title = t(`widget.${name}.title`, { defaultValue: name });

  return (
    <section className={`card ${open ? "" : "collapsed"}`}>
      <header>
        <h3>
          {title} <span className="muted">· {name}</span>
        </h3>
        <div className="spacer" />
        <label className="inline">
          <input
            type="checkbox"
            checked={settings.enabled}
            onChange={(e) => onChange({ ...settings, enabled: e.target.checked })}
          />
          {t("modules.enabled")}
        </label>
        <button className="btn small ghost" type="button" onClick={() => setOpen((v) => !v)}>
          {open ? "▲" : "▼"}
        </button>
      </header>

      <div className="card-body">
        <div className="row">
          <label htmlFor={`${name}-interval`}>{t("modules.interval")}</label>
          <div className="control">
            <div className="inline">
              <input
                id={`${name}-interval`}
                type="number"
                min={0.05}
                step={0.05}
                value={settings.interval ?? ""}
                placeholder={t("modules.interval_default")}
                onChange={(e) =>
                  onChange({
                    ...settings,
                    interval: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
              <span className="muted">{t("modules.interval_seconds")}</span>
            </div>
            <div className="hint">{t("modules.interval_help")}</div>
          </div>
        </div>

        {schema.length === 0 ? (
          <p className="muted" style={{ margin: "12px 0 0" }}>
            {t("modules.no_extra_settings")}
          </p>
        ) : (
          schema.map((field) => (
            <Field
              key={field.key}
              field={field}
              value={readPath(settings, field.key)}
              onChange={(value) =>
                onChange(writePath(settings, field.key, value) as ModuleSettings)
              }
            />
          ))
        )}
      </div>
    </section>
  );
}

/**
 * One input, decided by the module's own schema. This is the whole point of
 * `settings_schema`: a module gains an editable option by declaring it, and no
 * code in this window changes.
 */
function Field({
  field,
  value,
  onChange,
}: {
  field: SettingField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation();
  const label = t(field.label_key, { defaultValue: field.key });
  const help = field.help_key ? t(field.help_key, { defaultValue: "" }) : "";
  const id = `field-${field.label_key}`;

  let control: React.ReactNode;
  switch (field.type) {
    case "bool":
      control = (
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
      );
      break;
    case "int":
    case "float":
      control = (
        <input
          id={id}
          type="number"
          value={value === null || value === undefined ? "" : String(value)}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? (field.type === "int" ? 1 : "any")}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      );
      break;
    case "select":
      control = (
        <select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
      break;
    case "list":
      control = (
        <ListField
          values={Array.isArray(value) ? (value as string[]) : []}
          onChange={onChange}
        />
      );
      break;
    default:
      control = (
        <input
          id={id}
          type={field.secret ? "password" : "text"}
          value={String(value ?? "")}
          placeholder={
            field.placeholder_key ? t(field.placeholder_key, { defaultValue: "" }) : undefined
          }
          onChange={(e) => onChange(e.target.value)}
          onFocus={(e) => {
            // A masked secret is not a value anyone wants to edit character by
            // character — clear it on focus so typing replaces it, and leaving
            // it untouched keeps the mask (and therefore the stored secret).
            if (field.secret && e.target.value === SECRET_MASK) onChange("");
          }}
        />
      );
  }

  return (
    <div className="row">
      <label htmlFor={id}>{label}</label>
      <div className="control">
        {control}
        {field.secret && value === SECRET_MASK && (
          <div className="hint">{t("modules.secret_unchanged")}</div>
        )}
        {help && <div className="hint">{help}</div>}
      </div>
    </div>
  );
}

function ListField({
  values,
  onChange,
}: {
  values: string[];
  onChange: (value: string[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      {values.length === 0 && <div className="hint">{t("modules.list_empty")}</div>}
      {values.map((entry, index) => (
        <div className="list-row" key={index}>
          <input
            value={entry}
            onChange={(e) =>
              onChange(values.map((v, i) => (i === index ? e.target.value : v)))
            }
          />
          <button
            className="btn small ghost"
            type="button"
            title={t("common.remove")}
            onClick={() => onChange(values.filter((_, i) => i !== index))}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        className="btn small"
        type="button"
        style={{ marginTop: 6 }}
        onClick={() => onChange([...values, ""])}
      >
        {t("common.add")}
      </button>
    </div>
  );
}
