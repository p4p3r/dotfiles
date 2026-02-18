-- if true then return {} end -- WARN: REMOVE THIS LINE TO ACTIVATE THIS FILE

-- AstroCommunity: import any community modules here
-- We import this file in `lazy_setup.lua` before the `plugins/` folder.
-- This guarantees that the specs are processed before any user plugins.

---@type LazySpec
return {
  "AstroNvim/astrocommunity",
  --
  -- import/override with your plugins folder
  --
  -- Themes
  { import = "astrocommunity.colorscheme.catppuccin", enabled = false },
  { import = "astrocommunity.colorscheme.kanagawa-nvim", enabled = false },
  { import = "astrocommunity.colorscheme.rose-pine" },
  -- Packs
  { import = "astrocommunity.pack.lua" },
  { import = "astrocommunity.pack.python-ruff" },
  { import = "astrocommunity.pack.rust" },
  { import = "astrocommunity.pack.typescript" },
  { import = "astrocommunity.pack.json" },
  { import = "astrocommunity.pack.yaml" },
  -- Motion
  { import = "astrocommunity.motion.hop-nvim" },
  -- Window
  { import = "astrocommunity.split-and-window.minimap-vim" },
  -- AI
  { import = "astrocommunity.ai.sidekick-nvim" },
  -- Completion
  { import = "astrocommunity.recipes.ai" },
  { import = "astrocommunity.completion.copilot-cmp" },
  { import = "astrocommunity.completion.avante-nvim", enabled = false },
  -- Editing
  { import = "astrocommunity.editing-support.bigfile-nvim" },
  { import = "astrocommunity.editing-support.rainbow-delimiters-nvim" },
  { import = "astrocommunity.editing-support.yanky-nvim" },
  -- VSCode
  -- { import = "astrocommunity.recipes.vscode" },
}
