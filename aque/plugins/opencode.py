"""OpenCode plugin for aque.

Writes a JS plugin to ~/.config/opencode/plugins/aque.js that fires on
session.status idle and writes a signal file.
"""

from pathlib import Path

DEFAULT_PLUGIN_PATH = Path.home() / ".config" / "opencode" / "plugins" / "aque.js"

PLUGIN_JS = """\
export const AquePlugin = async ({ $ }) => ({
  event: async ({ event }) => {
    if (event.type === "session.status" && event.properties?.status?.type === "idle") {
      const id = process.env.AQUE_AGENT_ID
      if (id) {
        const dir = `${process.env.HOME}/.aque/signals`
        await $`mkdir -p ${dir}`
        await $`echo '{"event":"stop"}' > ${dir}/${id}.json`
      }
    }
  },
})
"""


def is_installed(plugin_path: Path = DEFAULT_PLUGIN_PATH) -> bool:
    return plugin_path.exists()


def install_hook(plugin_path: Path = DEFAULT_PLUGIN_PATH) -> None:
    if is_installed(plugin_path=plugin_path):
        return
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(PLUGIN_JS)
