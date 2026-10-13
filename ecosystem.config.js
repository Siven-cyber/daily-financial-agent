// PM2 process config for the Daily Financial Agent Telegram bot.
// Consistent with the other services on this server (lapakvip-router, storebot, ...).
//
// The bot is a long-running Python process. PM2 keeps it alive (autorestart) and
// captures logs, viewable with `pm2 logs finance-bot`. run_bot.sh handles venv
// activation, .env loading, and PYTHONPATH, so the unit stays a single command.
module.exports = {
  apps: [
    {
      name: "finance-bot",
      cwd: "/root/daily-financial-agent",
      script: "run_bot.sh",
      interpreter: "bash",
      autorestart: true,
      // If it crashes repeatedly in a short window, back off instead of looping.
      min_uptime: 10000,
      max_restarts: 15,
      exp_backoff_restart_delay: 200,
      kill_timeout: 10000,
    },
  ],
};
