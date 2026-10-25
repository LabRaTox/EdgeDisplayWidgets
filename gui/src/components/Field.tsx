import { useTranslation } from "react-i18next";

import type { SettingField } from "../types";

/**
 * The mask the backend substitutes for a stored secret. Sending it back
 * unchanged means "leave the stored value alone", which is exactly what
 * should happen when nobody typed in the field.
 */
const SECRET_MASK = "***";

/** Read a dotted path like "govee.api_key" out of a module's settings. */
export function readPath(source: Record<string, unknown>, key: string): unknown {
  return key.split(".").reduce<unknown>((value, part) => {
    if (value && typeof value === "object") {
      return (value as Record<string, unknown>)[part];
    }
    return undefined;
  }, source);
}

/** Write a dotted path, creating the intermediate objects it needs. */
export function writePath(
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

/**
 * One input, decided by a schema rather than written out here. That is the
 * whole point: a module gains an editable option by declaring it in
 * `settings_schema`, a widget by declaring it in its manifest, and this
 * window renders both without a line of code changing.
 *
 * Used by the layout editor for widget options and by the widget page for
 * module settings.
 */
/**
 * Whether a field applies, given the values of the fields beside it. A field
 * with `depends_on` is shown only while each named field has the given value,
 * or one of the given values when a list is named. Unset fields count with
 * their default.
 */
export function applies(
  field: SettingField,
  fields: SettingField[],
  valueOf: (key: string) => unknown,
): boolean {
  if (!field.depends_on) return true;
  return Object.entries(field.depends_on).every(([key, wanted]) => {
    const other = fields.find((f) => f.key === key);
    const current = valueOf(key) ?? other?.default;
    return Array.isArray(wanted) ? wanted.includes(current) : current === wanted;
  });
}

export function Field({
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
          {(field.options ?? []).map((option, index) => (
            <option key={option} value={option}>
              {/*
                * The value doubles as the label unless the schema says
                * otherwise: a sensor id reads as `hwmon3/k10temp:1`, which is
                * the right thing to store and the wrong thing to show.
                */}
              {field.option_labels?.[index] ??
                (field.option_label_keys?.[index]
                  ? t(field.option_label_keys[index], { defaultValue: option })
                  : option)}
            </option>
          ))}
        </select>
      );
      break;
    case "color":
      /*
       * An empty value is not a colour but the absence of one, and a colour
       * well cannot show that: it would sit on black and look like a choice
       * nobody made. So the well falls back to a neutral swatch and the cross
       * next to it puts the field back to empty, which is what "use the
       * theme's colour" looks like.
       */
      control = (
        <span className="control inline">
          <input
            id={id}
            type="color"
            value={String(value || "#808080")}
            onChange={(e) => onChange(e.target.value)}
          />
          {value ? (
            <button
              className="btn small ghost"
              type="button"
              title={t("common.reset")}
              onClick={() => onChange("")}
            >
              ✕
            </button>
          ) : null}
        </span>
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
