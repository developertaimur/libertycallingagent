/**
 * Phone-style double-ring for live transfer desk alerts.
 * Browsers require a user gesture before AudioContext can play — call unlock().
 */

type Ctx = AudioContext;

let sharedCtx: Ctx | null = null;
let ringTimer: number | null = null;
let unlocked = false;

function getCtx(): Ctx | null {
  if (typeof window === "undefined") return null;
  const AC =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext;
  if (!AC) return null;
  if (!sharedCtx) sharedCtx = new AC();
  return sharedCtx;
}

/** Call from any click/keydown so later transfer rings are allowed. */
export async function unlockTransferAudio(): Promise<boolean> {
  try {
    const ctx = getCtx();
    if (!ctx) return false;
    if (ctx.state === "suspended") await ctx.resume();
    // Silent blip so Chrome marks the context as user-activated
    const g = ctx.createGain();
    g.gain.value = 0.0001;
    const o = ctx.createOscillator();
    o.connect(g);
    g.connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.01);
    unlocked = true;
    return true;
  } catch {
    return false;
  }
}

export function isTransferAudioUnlocked(): boolean {
  return unlocked && sharedCtx?.state === "running";
}

function tone(
  ctx: Ctx,
  freq: number,
  start: number,
  dur: number,
  peak = 0.22,
): void {
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = "sine";
  o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, start);
  g.gain.exponentialRampToValueAtTime(peak, start + 0.02);
  g.gain.setValueAtTime(peak, start + dur - 0.04);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  o.connect(g);
  g.connect(ctx.destination);
  o.start(start);
  o.stop(start + dur + 0.02);
}

/** One classic US-style ring burst: dual tone ~2s, then silence until next cycle. */
function playRingBurst(ctx: Ctx): void {
  const t0 = ctx.currentTime + 0.02;
  // Dual-tone (approx North American ringback-ish: 440 + 480)
  for (const f of [440, 480]) {
    tone(ctx, f, t0, 0.4);
    tone(ctx, f, t0 + 0.55, 0.4);
  }
}

export function startTransferRingtone(): void {
  stopTransferRingtone();
  const ctx = getCtx();
  if (!ctx) return;
  void ctx.resume().then(() => {
    playRingBurst(ctx);
    // Repeat every ~2.8s while alert is open
    ringTimer = window.setInterval(() => {
      if (ctx.state !== "running") {
        void ctx.resume();
      }
      playRingBurst(ctx);
    }, 2800);
  });
}

export function stopTransferRingtone(): void {
  if (ringTimer != null) {
    window.clearInterval(ringTimer);
    ringTimer = null;
  }
}
