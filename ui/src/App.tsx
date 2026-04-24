import { For, Show, createEffect, createMemo, createSignal, onCleanup, onMount } from "solid-js";
import { actionEngine, addStrategy, eventsWsUrl, getEngines, getMetrics, toggleStrategy, type Engine } from "./api";

export default function App() {
  const [engines, setEngines] = createSignal<Engine[]>([]);
  const [metrics, setMetrics] = createSignal<Record<string, unknown>>({});
  const [events, setEvents] = createSignal<string[]>([]);
  const [selectedEngine, setSelectedEngine] = createSignal<string>("");
  const [newStrategy, setNewStrategy] = createSignal<string>("");
  const [busy, setBusy] = createSignal(false);

  const selected = createMemo(() => engines().find((e) => e.engine_id === selectedEngine()));

  async function refresh() {
    const [e, m] = await Promise.all([getEngines(), getMetrics()]);
    setEngines(e);
    if (!selectedEngine() && e.length) setSelectedEngine(e[0].engine_id);
    setMetrics(m);
  }

  async function doAction(engineId: string, action: "start" | "stop" | "restart") {
    setBusy(true);
    try {
      await actionEngine(engineId, action);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function onToggle(strategy: string, enabled: boolean) {
    if (!selected()) return;
    await toggleStrategy(selected()!.engine_id, strategy, enabled);
    await refresh();
  }

  async function onAddStrategy() {
    if (!selected() || !newStrategy().trim()) return;
    await addStrategy(selected()!.engine_id, newStrategy().trim());
    setNewStrategy("");
    await refresh();
  }

  onMount(async () => {
    await refresh();
    const ws = new WebSocket(eventsWsUrl());
    ws.onmessage = (ev) => {
      setEvents((prev) => [...prev.slice(-199), ev.data]);
    };
    onCleanup(() => ws.close());
  });

  createEffect(() => {
    const id = setInterval(() => {
      refresh().catch(() => undefined);
    }, 5000);
    onCleanup(() => clearInterval(id));
  });

  return (
    <div class="min-h-full bg-base-200 text-base-content">
      <header class="navbar bg-base-100 shadow">
        <div class="flex-1 px-4 text-xl font-semibold">Trading Control & Monitor</div>
        <div class="px-4 text-sm opacity-70">SolidJS + DaisyUI</div>
      </header>

      <main class="grid grid-cols-1 gap-4 p-4 xl:grid-cols-3">
        <section class="card bg-base-100 shadow xl:col-span-2">
          <div class="card-body">
            <h2 class="card-title">Engines</h2>
            <div class="overflow-x-auto">
              <table class="table">
                <thead>
                  <tr>
                    <th>Engine</th>
                    <th>Venue</th>
                    <th>Status</th>
                    <th>Strategies</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  <For each={engines()}>
                    {(e) => (
                      <tr class={selectedEngine() === e.engine_id ? "active" : ""}>
                        <td>
                          <button class="link" onClick={() => setSelectedEngine(e.engine_id)}>
                            {e.engine_id}
                          </button>
                        </td>
                        <td>{e.venue}</td>
                        <td>
                          <span class={`badge ${e.runtime_status === "running" ? "badge-success" : "badge-ghost"}`}>
                            {e.runtime_status}
                          </span>
                        </td>
                        <td>{e.strategies.join(", ")}</td>
                        <td class="space-x-2">
                          <button class="btn btn-xs btn-success" disabled={busy()} onClick={() => doAction(e.engine_id, "start")}>
                            Start
                          </button>
                          <button class="btn btn-xs btn-warning" disabled={busy()} onClick={() => doAction(e.engine_id, "restart")}>
                            Restart
                          </button>
                          <button class="btn btn-xs btn-error" disabled={busy()} onClick={() => doAction(e.engine_id, "stop")}>
                            Stop
                          </button>
                        </td>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="card bg-base-100 shadow">
          <div class="card-body">
            <h2 class="card-title">Droplet Metrics</h2>
            <div class="space-y-2 text-sm">
              <div>CPU: {String(metrics().cpu_percent ?? "-")}%</div>
              <div>Memory: {String(metrics().memory_percent ?? "-")}%</div>
              <div>Disk: {String(metrics().disk_percent ?? "-")}%</div>
              <div>Load(1m): {String((metrics().load_avg as any)?.["1m"] ?? "-")}</div>
            </div>
          </div>
        </section>

        <section class="card bg-base-100 shadow xl:col-span-1">
          <div class="card-body">
            <h2 class="card-title">Strategy Controls</h2>
            <Show when={selected()} fallback={<div class="text-sm opacity-70">Select an engine first.</div>}>
              {(eng) => (
                <>
                  <div class="text-sm opacity-70">Engine: {eng().engine_id}</div>
                  <For each={eng().strategies}>
                    {(s) => (
                      <div class="form-control">
                        <label class="label cursor-pointer">
                          <span class="label-text">{s}</span>
                          <input class="toggle" type="checkbox" checked onChange={(ev) => onToggle(s, ev.currentTarget.checked)} />
                        </label>
                      </div>
                    )}
                  </For>
                  <div class="join mt-3">
                    <input
                      class="input input-bordered join-item input-sm"
                      placeholder="New strategy name"
                      value={newStrategy()}
                      onInput={(e) => setNewStrategy(e.currentTarget.value)}
                    />
                    <button class="btn btn-primary btn-sm join-item" onClick={onAddStrategy}>
                      Add
                    </button>
                  </div>
                </>
              )}
            </Show>
          </div>
        </section>

        <section class="card bg-base-100 shadow xl:col-span-2">
          <div class="card-body">
            <h2 class="card-title">Live Event Stream</h2>
            <div class="mockup-code max-h-[28rem] overflow-auto text-xs">
              <For each={events()}>
                {(line) => <pre>{line}</pre>}
              </For>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

