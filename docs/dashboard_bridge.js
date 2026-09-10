/**
 * Shared Supabase bridge for static dashboard → git Actions.
 * One channel + commands table for all page-triggered workflows.
 */
(function initDashboardBridge(global) {
  const DEFAULT_CHANNEL = "ftse-dashboard";
  let config = null;
  let client = null;
  let broadcastChannel = null;
  let artifactListeners = [];

  async function loadConfig() {
    try {
      const response = await fetch(`data/dashboard_config.json?ts=${Date.now()}`, {
        cache: "no-store",
      });
      if (!response.ok) return null;
      const payload = await response.json();
      return payload && payload.enabled ? payload : null;
    } catch {
      return null;
    }
  }

  function ensureSupabaseJs() {
    return new Promise((resolve, reject) => {
      if (global.supabase && global.supabase.createClient) {
        resolve(global.supabase);
        return;
      }
      const existing = document.querySelector('script[data-supabase-js="1"]');
      if (existing) {
        existing.addEventListener("load", () => resolve(global.supabase));
        existing.addEventListener("error", () => reject(new Error("Supabase JS failed to load")));
        return;
      }
      const script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js";
      script.async = true;
      script.dataset.supabaseJs = "1";
      script.onload = () => resolve(global.supabase);
      script.onerror = () => reject(new Error("Supabase JS failed to load"));
      document.head.appendChild(script);
    });
  }

  async function init() {
    if (client) return true;
    config = await loadConfig();
    if (!config || !config.supabase_url || !config.supabase_anon_key) {
      return false;
    }
    const supabaseLib = await ensureSupabaseJs();
    client = supabaseLib.createClient(config.supabase_url, config.supabase_anon_key);
    const channelName = String(config.channel || DEFAULT_CHANNEL);
    broadcastChannel = client.channel(channelName, {
      config: { broadcast: { self: false } },
    });
    broadcastChannel.on("broadcast", { event: "artifact-updated" }, (message) => {
      const payload = message.payload || {};
      for (const listener of artifactListeners) {
        try {
          listener(payload);
        } catch {
          /* ignore listener errors */
        }
      }
    });
    broadcastChannel.subscribe();
    return true;
  }

  function isEnabled() {
    return Boolean(config && config.enabled && client);
  }

  function onArtifactUpdated(listener) {
    artifactListeners.push(listener);
    return () => {
      artifactListeners = artifactListeners.filter((fn) => fn !== listener);
    };
  }

  function waitForCommandRow(commandId, onStatus, timeoutMs) {
    const table = String(config.commands_table || "dashboard_commands");
    const deadline = Date.now() + (timeoutMs || 12 * 60 * 1000);
    return new Promise((resolve, reject) => {
      const channel = client
        .channel(`cmd-${commandId}`)
        .on(
          "postgres_changes",
          {
            event: "UPDATE",
            schema: "public",
            table,
            filter: `id=eq.${commandId}`,
          },
          (payload) => {
            const row = payload.new || {};
            const status = String(row.status || "");
            if (onStatus && row.message) onStatus(row.message);
            if (status === "done") {
              channel.unsubscribe();
              resolve(row);
            } else if (status === "failed") {
              channel.unsubscribe();
              reject(new Error(row.message || "Dashboard command failed"));
            }
          }
        )
        .subscribe();

      const poll = async () => {
        while (Date.now() < deadline) {
          const { data, error } = await client.from(table).select("*").eq("id", commandId).maybeSingle();
          if (error) {
            reject(error);
            return;
          }
          if (data) {
            const status = String(data.status || "");
            if (onStatus && data.message) onStatus(data.message);
            if (status === "done") {
              channel.unsubscribe();
              resolve(data);
              return;
            }
            if (status === "failed") {
              channel.unsubscribe();
              reject(new Error(data.message || "Dashboard command failed"));
              return;
            }
          }
          await new Promise((r) => setTimeout(r, 4000));
        }
        channel.unsubscribe();
        reject(new Error("Timed out waiting for dashboard command"));
      };
      void poll();
    });
  }

  async function submitCommand(action, payload, onStatus) {
    const ready = await init();
    if (!ready) {
      throw new Error("BRIDGE_DISABLED");
    }
    const table = String(config.commands_table || "dashboard_commands");
    const body = {
      action,
      payload: payload || {},
      status: "pending",
    };
    if (onStatus) onStatus("Submitting dashboard command…");
    const { data, error } = await client.from(table).insert(body).select("*").single();
    if (error) {
      throw new Error(error.message || "Could not insert dashboard command");
    }
    const commandId = data.id;
    if (broadcastChannel) {
      await broadcastChannel.send({
        type: "broadcast",
        event: "command",
        payload: { v: 1, id: commandId, action, payload: body.payload },
      });
    }
    if (onStatus) onStatus("Queued — waiting for GitHub worker…");
    return waitForCommandRow(commandId, onStatus);
  }

  global.DashboardBridge = {
    init,
    isEnabled,
    submitCommand,
    onArtifactUpdated,
  };
})(window);
