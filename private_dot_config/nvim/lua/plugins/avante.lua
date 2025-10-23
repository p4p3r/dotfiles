---@type LazySpec
return {
  -- -- You can also easily customize additional setup of plugins that is outside of the plugin's setup call
  {
    "yetone/avante.nvim",
    opts = { -- extend the plugin options
      provider = "openai",
      openai = {
        endpoint = "https://api.openai.com/v1",
        model = "o4-mini", -- your desired model (or use gpt-4o, etc.)
        api_key_name = "OPENAI_API_KEY",
        -- api_key_name = "cmd:op read op://personal/OpenAI/credential --no-newline",
        timeout = 30000, -- timeout in milliseconds
        temperature = 0, -- adjust if needed
        max_completion_tokens = 4096,
        -- reasoning_effort = "high" -- only supported for reasoning models (o1, etc.)
      },
    },
  },
}
