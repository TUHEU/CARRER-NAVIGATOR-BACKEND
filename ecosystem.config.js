// PM2 ecosystem config — Career Navigator
// Usage: pm2 start ecosystem.config.js
module.exports = {
  apps: [
    {
      name: "career-navigator-api",
      script: "app.py",
      interpreter: "python3",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "300M",
      env: {
        FLASK_ENV: "production",
      },
      error_file: "./logs/err.log",
      out_file:   "./logs/out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
  ],
};
