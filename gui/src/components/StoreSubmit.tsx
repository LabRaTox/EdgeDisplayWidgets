import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useDropZone } from "../lib/dropZone";
import type { StoreMine, StoreUploadResult, StoreUser } from "../types";
import { Modal } from "./Modal";

type MinePlugin = StoreMine["plugins"][number];
type MineVersion = MinePlugin["versions"][number];

/**
 * A version number as numbers: `"1.10.2"` is `[1, 10, 2]`. Counted the same
 * way as the store and the backend, so everyone agrees on the newest.
 */
function asNumbers(version: string): number[] {
  const parts = String(version || "")
    .split(".")
    .map((piece) => {
      const digits = /^\d+/.exec(piece);
      return digits ? Number(digits[0]) : 0;
    });
  return parts.length > 0 ? parts : [0];
}

function compareVersions(a: string, b: string): number {
  const x = asNumbers(a);
  const y = asNumbers(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const difference = (x[i] ?? 0) - (y[i] ?? 0);
    if (difference !== 0) return difference;
  }
  return 0;
}

/** Versions from the highest number to the lowest, as in the store. */
function byNumber(versions: MineVersion[]): MineVersion[] {
  return [...versions].sort((a, b) => compareVersions(b.version, a.version));
}

function message(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc);
}

/**
 * Submitting, and seeing what became of it.
 *
 * Both in one dialog, because it is the same question: what did I put into
 * the store, and where does it stand? Whoever sees only one of the two
 * submits twice when in doubt.
 */
export function StoreSubmit({ user, onClose }: { user: StoreUser | null; onClose: () => void }) {
  const { t } = useTranslation();
  const [mine, setMine] = useState<MinePlugin[] | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState("");
  const [result, setResult] = useState<StoreUploadResult | null>(null);
  const [selected, setSelected] = useState("");

  // Without a choice of its own, the first plugin stands on the right, so
  // the side is not empty. If the chosen one disappears (withdrawn and
  // deleted), the first one moves up as well.
  const chosen = mine?.find((p) => p.slug === selected) ?? mine?.[0] ?? null;

  const fetchMine = useCallback(async () => {
    try {
      setMine((await api.storeMine()).plugins);
    } catch (exc) {
      setMine([]);
      setError(message(exc));
    }
  }, []);

  useEffect(() => {
    if (user) void fetchMine();
  }, [user, fetchMine]);

  async function submit(file: File) {
    setRunning(file.name);
    setError("");
    setResult(null);
    try {
      const answer = await api.storeUploadArchive(file);
      setResult(answer);
      // The plugin just submitted is what the right side shows next.
      setSelected(answer.slug);
      await fetchMine();
    } catch (exc) {
      setError(message(exc));
    } finally {
      setRunning("");
    }
  }

  async function withdraw(plugin: MinePlugin, version: MineVersion) {
    // Two different questions for two different things: what is approved
    // may already be installed somewhere.
    const question =
      version.status === "approved"
        ? t("submit.withdraw_confirm", { name: plugin.name, version: version.version })
        : t("submit.delete_confirm", { name: plugin.name, version: version.version });
    if (!window.confirm(question)) return;

    setError("");
    try {
      await api.storeWithdraw(plugin.slug, version.version);
      await fetchMine();
    } catch (exc) {
      setError(message(exc));
    }
  }

  if (!user) {
    return (
      <Modal title={t("widgets.submit")} onClose={onClose}>
        <p className="hint">{t("submit.needs_login")}</p>
      </Modal>
    );
  }

  return (
    <Modal title={t("widgets.submit")} onClose={onClose} width={960}>
      {error && <p className="error-note">{error}</p>}

      {result && (
        <div className={result.status === "approved" ? "store-receipt good" : "store-receipt"}>
          <strong>
            {result.slug} {result.version}
          </strong>
          <p>{result.message}</p>
          {/* The author learns about findings at once, not by concluding
              from a rejection that someone found something. */}
          {result.warnings > 0 && (
            <p className="hint">{t("submit.findings", { count: result.warnings })}</p>
          )}
        </div>
      )}

      <h4>{t("submit.pick")}</h4>
      <DropZone running={!!running} onFile={(file) => void submit(file)} onError={setError} />
      <p className="hint">{t("submit.formats")}</p>

      <h4>{t("submit.mine")}</h4>
      {mine === null ? (
        <p className="hint">{t("common.loading")}</p>
      ) : mine.length === 0 ? (
        <p className="hint">{t("submit.mine_empty")}</p>
      ) : (
        <div className="submit-grid">
          <ul className="submit-list">
            {mine.map((plugin) => {
              const newest = byNumber(plugin.versions)[0];
              const waiting = plugin.versions.filter((v) => v.status === "pending").length;
              return (
                <li key={plugin.slug}>
                  <button
                    type="button"
                    className={plugin.slug === chosen?.slug ? "submit-entry active" : "submit-entry"}
                    onClick={() => setSelected(plugin.slug)}
                  >
                    <span className="submit-entry-name">
                      <strong>{plugin.name}</strong>
                      <span className="hint">{plugin.slug}</span>
                    </span>
                    <span className="submit-entry-state">
                      {plugin.removedAt ? (
                        <span className="state-tag blocked">{t("submit.blocked")}</span>
                      ) : (
                        newest && (
                          <>
                            <span className="code">{newest.version}</span>
                            <span className={`state-tag ${newest.status}`}>
                              {t(`submit.status.${newest.status}`)}
                            </span>
                          </>
                        )
                      )}
                      {waiting > 0 && newest?.status !== "pending" && (
                        <span className="state-tag pending">
                          {t("submit.waiting", { count: waiting })}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="submit-detail">
            {chosen ? (
              <Versions plugin={chosen} onWithdraw={(v) => void withdraw(chosen, v)} />
            ) : (
              <p className="hint">{t("submit.mine_select")}</p>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

/**
 * The versions of one of your own plugins, beside the list.
 *
 * Fixed columns, so date and downloads stand in the same place for every
 * version. The moderator's note gets a row of its own underneath; a long
 * text would otherwise push every other column aside.
 */
function Versions({
  plugin,
  onWithdraw,
}: {
  plugin: MinePlugin;
  onWithdraw: (version: MineVersion) => void;
}) {
  const { t } = useTranslation();
  const versions = byNumber(plugin.versions);

  return (
    <>
      <div className="store-mine-head">
        <strong>{plugin.name}</strong>
        <span className="hint">{plugin.slug}</span>
        {plugin.removedAt ? (
          <span className="state-tag blocked">{t("submit.blocked")}</span>
        ) : (
          plugin.visibility !== "listed" && (
            <span className="tag-store">{t(`submit.visibility.${plugin.visibility}`)}</span>
          )
        )}
      </div>
      {plugin.removedAt && plugin.removedReason && (
        <p className="error-note">{plugin.removedReason}</p>
      )}

      {versions.length === 0 ? (
        <p className="hint">{t("submit.no_versions")}</p>
      ) : (
        <table className="store-versions">
          <colgroup>
            <col style={{ width: "16%" }} />
            <col style={{ width: "26%" }} />
            <col style={{ width: "20%" }} />
            <col style={{ width: "14%" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th>{t("submit.col_version")}</th>
              <th>{t("submit.col_status")}</th>
              <th>{t("submit.col_date")}</th>
              <th>{t("submit.col_downloads")}</th>
              <th />
            </tr>
          </thead>
          {versions.map((v) => {
            // The moderator's text stands here and nowhere else: the store
            // does not accept a rejection without a reason.
            const note = v.reviewNote || v.stateNote || "";
            return (
              <tbody key={v.version}>
                <tr>
                  <td className="code">{v.version}</td>
                  <td>
                    <span className={`state-tag ${v.status}`}>{t(`submit.status.${v.status}`)}</span>
                  </td>
                  <td className="hint">
                    {new Date(v.reviewedAt ?? v.submittedAt).toLocaleDateString()}
                  </td>
                  <td className="hint">{v.downloadCount} ×</td>
                  <td className="store-version-button">
                    {/* Blocked and already withdrawn versions cannot be
                        touched in the store, so there is no button that
                        would only bring an error. */}
                    {(v.status === "pending" || v.status === "rejected" || v.status === "approved") && (
                      <button type="button" className="btn small danger" onClick={() => onWithdraw(v)}>
                        {t(v.status === "approved" ? "submit.withdraw" : "submit.delete")}
                      </button>
                    )}
                  </td>
                </tr>
                {note && (
                  <tr className="store-version-note">
                    <td colSpan={5} className="hint">
                      {note}
                    </td>
                  </tr>
                )}
              </tbody>
            );
          })}
        </table>
      )}
    </>
  );
}

/**
 * The field the archive goes into.
 *
 * Drag or click, both lead to the same. A dialog with only a choose button
 * would look as if dragging did not work, and that is what everyone tries
 * first.
 */
function DropZone({
  running,
  onFile,
  onError,
}: {
  running: boolean;
  onFile: (file: File) => void;
  onError: (text: string) => void;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);

  function take(files: ArrayLike<File> | null) {
    const file = files?.[0];
    if (file) onFile(file);
  }

  const drop = useDropZone({ onFiles: take, onError });

  return (
    <div
      ref={drop.ref}
      className={drop.over ? "drop-zone over" : "drop-zone"}
      {...drop.props}
      onClick={() => input.current?.click()}
    >
      <input
        ref={input}
        type="file"
        accept=".zip,.tar,.tar.gz,.tgz,application/zip,application/x-tar,application/gzip"
        hidden
        onChange={(e) => {
          take(e.target.files);
          // Reset, so the same file can be chosen a second time; otherwise
          // the browser fires no event.
          e.target.value = "";
        }}
      />
      <strong>{running ? t("submit.submitting") : t("submit.drop_here")}</strong>
      <span className="hint">{t("submit.drop_or_click")}</span>
    </div>
  );
}
