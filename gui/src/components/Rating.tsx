import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api } from "../api/client";
import type { StoreRating, StoreUser } from "../types";
import { Icon } from "./Icon";

function message(exc: unknown): string {
  return exc instanceof ApiError || exc instanceof Error ? exc.message : String(exc);
}

/**
 * How a plugin is received, and the chance to say so oneself.
 *
 * On both detail pages: for a plugin from the store and for one that is
 * installed. The installed one is the moment someone has an opinion, after
 * a few weeks of use, not while skimming the list.
 *
 * Two thumbs instead of five stars: with stars one ponders the difference
 * between three and four, and in the end everything stands at 4.2.
 */
export function Rating({ slug, user }: { slug: string; user: StoreUser | null }) {
  const { t } = useTranslation();
  const signedIn = Boolean(user);

  const [state, setState] = useState<StoreRating | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [comment, setComment] = useState("");
  const [writing, setWriting] = useState(false);
  // A thumbs down needs a reason. Until it is there, the vote is only noted
  // and not sent.
  const [downPending, setDownPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState(null);
    setError("");
    api
      .storeRating(slug)
      .then((data) => {
        if (cancelled) return;
        setState(data);
        setComment(data.comment ?? "");
      })
      // A plugin that is not (or no longer) in the store is not an error of
      // the page; then there is simply nothing to show.
      .catch((exc: unknown) => !cancelled && setError(message(exc)));
    return () => {
      cancelled = true;
    };
  }, [slug, user]);

  async function vote(value: 1 | -1) {
    if (!state || busy) return;
    if (value === -1 && state.mine !== -1 && !comment.trim()) {
      setDownPending(true);
      setWriting(true);
      setError("");
      return;
    }
    setBusy(true);
    setError("");
    try {
      // The same direction once more means: opinion withdrawn.
      const next =
        state.mine === value ? await api.storeUnrate(slug) : await api.storeRate(slug, value, comment);
      setState(next);
      setComment(next.comment ?? "");
      setDownPending(false);
      if (next.mine === null) setWriting(false);
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  async function saveComment() {
    const value = downPending ? -1 : state?.mine;
    if (!value || busy) return;
    if (value === -1 && !comment.trim()) {
      setError(t("rating.down_needs_reason"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await api.storeRate(slug, value as 1 | -1, comment);
      setState(next);
      setDownPending(false);
      setWriting(false);
    } catch (exc) {
      setError(message(exc));
    } finally {
      setBusy(false);
    }
  }

  if (error && !state) return null;
  if (!state) return <p className="hint">{t("rating.loading")}</p>;

  const others = state.comments.filter((c) => c.author !== user?.handle);
  // One does not rate one's own plugin; the store refuses it.
  const own = Boolean(state.own);
  const mayVote = signedIn && !own;
  const hint = own ? t("rating.own") : signedIn ? "" : t("rating.needs_login");

  return (
    <section className="rating">
      <h4>{t("rating.title")}</h4>

      <div className="rating-buttons">
        <button
          type="button"
          className={`btn thumb${state.mine === 1 ? " active" : ""}`}
          disabled={!mayVote || busy}
          title={hint || t("rating.up_hint")}
          onClick={() => void vote(1)}
        >
          <Icon icon="ti:thumb-up" />
          {state.up}
        </button>
        <button
          type="button"
          className={`btn thumb down${state.mine === -1 || downPending ? " active" : ""}`}
          disabled={!mayVote || busy}
          title={hint || t("rating.down_hint")}
          onClick={() => void vote(-1)}
        >
          <Icon icon="ti:thumb-down" />
          {state.down}
        </button>

        {hint && <span className="hint">{hint}</span>}
        {mayVote && state.mine !== null && !writing && (
          <button type="button" className="btn ghost" onClick={() => setWriting(true)}>
            {state.comment ? t("rating.edit_comment") : t("rating.add_comment")}
          </button>
        )}
      </div>

      {mayVote && (state.mine !== null || downPending) && writing && (
        <div className="rating-write">
          {downPending && <p className="hint">{t("rating.down_needs_reason")}</p>}
          <textarea
            value={comment}
            maxLength={500}
            rows={3}
            placeholder={t("rating.comment_placeholder")}
            onChange={(event) => setComment(event.target.value)}
          />
          <div className="inline">
            <button type="button" className="btn primary" disabled={busy} onClick={() => void saveComment()}>
              {t("common.save")}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setComment(state.comment ?? "");
                setDownPending(false);
                setWriting(false);
              }}
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      {error && <p className="error-text">{error}</p>}

      {state.comment && !writing && (
        <blockquote className="rating-own">
          <Icon icon={state.mine === -1 ? "ti:thumb-down" : "ti:thumb-up"} />
          {state.comment}
          <small>{t("rating.yours")}</small>
        </blockquote>
      )}

      {others.length > 0 && (
        <ul className="rating-list">
          {others.map((c, i) => (
            <li key={i}>
              <Icon icon={c.value === -1 ? "ti:thumb-down" : "ti:thumb-up"} />
              <span>{c.comment}</span>
              <small>
                {c.author} · {new Date(c.at).toLocaleDateString()}
              </small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
