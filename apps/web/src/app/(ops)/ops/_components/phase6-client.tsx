"use client";

// Client pieces for Phase 6: the signature pad (proof of delivery) and the tracking-link form that
// shows a new link exactly once.

import { useTranslations } from "next-intl";
import { useActionState, useRef, useState } from "react";

import { LINK_FIELDS, type Stroke, signaturePayload } from "@/lib/phase6";

import { type CreateLinkState, createTrackingLink, deliverWithEvidence } from "../phase6-actions";

const input =
  "w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";
const button =
  "inline-flex items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50";
const subtle = "inline-flex items-center rounded-md border px-3 py-2 text-sm hover:bg-muted";

const PAD_W = 320;
const PAD_H = 120;

function SignaturePad({ onChange }: { onChange: (json: string) => void }) {
  const t = useTranslations("Ops.delivery");
  const canvas = useRef<HTMLCanvasElement>(null);
  const strokes = useRef<Stroke[]>([]);
  const drawing = useRef(false);

  function point(e: React.PointerEvent<HTMLCanvasElement>): [number, number] {
    const r = e.currentTarget.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * PAD_W, ((e.clientY - r.top) / r.height) * PAD_H];
  }

  function publish() {
    const sig = signaturePayload(PAD_W, PAD_H, strokes.current);
    onChange(sig ? JSON.stringify(sig) : "");
  }

  function down(e: React.PointerEvent<HTMLCanvasElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    drawing.current = true;
    strokes.current.push([point(e)]);
  }

  function move(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const stroke = strokes.current[strokes.current.length - 1];
    const p = point(e);
    const prev = stroke[stroke.length - 1];
    stroke.push(p);
    const ctx = canvas.current?.getContext("2d");
    if (ctx && prev) {
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.strokeStyle = getComputedStyle(e.currentTarget).color;
      ctx.beginPath();
      ctx.moveTo(prev[0], prev[1]);
      ctx.lineTo(p[0], p[1]);
      ctx.stroke();
    }
  }

  function up() {
    drawing.current = false;
    publish();
  }

  function clear() {
    strokes.current = [];
    canvas.current?.getContext("2d")?.clearRect(0, 0, PAD_W, PAD_H);
    onChange("");
  }

  return (
    <div className="space-y-1">
      <canvas
        ref={canvas}
        width={PAD_W}
        height={PAD_H}
        aria-label={t("signature")}
        className="w-full max-w-xs touch-none rounded-md border bg-background text-foreground"
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
      />
      <button type="button" onClick={clear} className="text-xs underline-offset-4 hover:underline">
        {t("clear")}
      </button>
    </div>
  );
}

export function DeliverForm({ shipmentId, idempotencyKey }: { shipmentId: string; idempotencyKey: string }) {
  const t = useTranslations("Ops.delivery");
  const [signature, setSignature] = useState("");
  return (
    <form action={deliverWithEvidence} className="grid max-w-md gap-3 rounded-lg border p-3">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <input type="hidden" name="shipment_id" value={shipmentId} />
      <input type="hidden" name="signature" value={signature} />
      <p className="text-sm font-medium">{t("title")}</p>
      <label className="text-sm">
        <span className="mb-1 block">{t("recipient")}</span>
        <input name="recipient" required maxLength={200} className={input} />
      </label>
      <label className="text-sm">
        <span className="mb-1 block">{t("photo")}</span>
        <input name="photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" required className="text-sm" />
      </label>
      <div className="text-sm">
        <span className="mb-1 block">{t("signature")}</span>
        <SignaturePad onChange={setSignature} />
      </div>
      <p className="text-xs text-muted-foreground">{t("note")}</p>
      <button type="submit" disabled={!signature} className={button}>
        {t("confirm")}
      </button>
    </form>
  );
}

export function CreateLinkForm({ shipmentId, idempotencyKey }: { shipmentId: string; idempotencyKey: string }) {
  const t = useTranslations("Ops.links");
  const [state, action, pending] = useActionState<CreateLinkState, FormData>(createTrackingLink, {});
  const [copied, setCopied] = useState(false);
  if (state.url) {
    return (
      <div role="status" className="max-w-xl space-y-2 rounded-lg border border-emerald-500/40 p-3 text-sm">
        <p className="font-medium">{t("created")}</p>
        <input readOnly value={state.url} className={input} onFocus={(e) => e.currentTarget.select()} />
        <div className="flex gap-2">
          <button
            type="button"
            className={subtle}
            onClick={() => {
              void navigator.clipboard?.writeText(state.url ?? "").then(() => setCopied(true));
            }}
          >
            {copied ? t("copied") : t("copy")}
          </button>
        </div>
        <p className="text-xs text-muted-foreground">{t("onlyOnce")}</p>
      </div>
    );
  }
  return (
    <form action={action} className="grid max-w-xl gap-3 rounded-lg border p-3 text-sm">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <input type="hidden" name="shipment_id" value={shipmentId} />
      <div className="grid gap-3 sm:grid-cols-2">
        <label>
          <span className="mb-1 block">{t("label")}</span>
          <input name="label" maxLength={120} className={input} placeholder={t("labelHint")} />
        </label>
        <label>
          <span className="mb-1 block">{t("expires")}</span>
          <input name="expires_in_days" type="number" min={1} max={90} defaultValue={30} className={input} />
        </label>
      </div>
      <fieldset>
        <legend className="mb-1">{t("fields")}</legend>
        <div className="flex flex-wrap gap-3">
          {LINK_FIELDS.map((f) => (
            <label key={f} className="inline-flex items-center gap-1">
              <input type="checkbox" name="fields" value={f} defaultChecked />
              {t(`field.${f}`)}
            </label>
          ))}
        </div>
      </fieldset>
      {state.error ? (
        <p role="alert" className="text-destructive">
          {t("error")} <code>{state.error}</code>
          {state.requestId ? ` · ${state.requestId}` : ""}
        </p>
      ) : null}
      <div>
        <button type="submit" disabled={pending} className={button}>
          {t("create")}
        </button>
      </div>
    </form>
  );
}
