"""Allow running the bot as a script: python -m finance_agent.

PM2 launches this file directly (see ecosystem.config.js), which then delegates to
bot.main() so the package can also still be run as `python -m finance_agent.bot`.
"""

from .bot import main

if __name__ == "__main__":
    raise SystemExit(main())
