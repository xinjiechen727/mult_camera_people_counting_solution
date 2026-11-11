const path = require("node:path");

const root = process.env.PROJECT_ROOT || __dirname;
const app = path.join(root, "app");

module.exports = {
  apps: [
    {
      name: "people-counting-dashboard",
      script: path.join(app, "dist", "boot.js"),
      cwd: app,
      interpreter: "node",
      autorestart: true,
      restart_delay: 5000,
      env: { NODE_ENV: "production", PROJECT_ROOT: root },
    },
    {
      name: "yolo-detector",
      script: path.join(root, "main.py"),
      cwd: root,
      interpreter: "python3",
      autorestart: true,
      restart_delay: 5000,
      env: { PROJECT_ROOT: root },
    },
    {
      name: "recamera-puller",
      script: path.join(root, "recamera_puller.py"),
      cwd: root,
      interpreter: "python3",
      autorestart: true,
      restart_delay: 3000,
      env: { PROJECT_ROOT: root },
    },
    {
      name: "watchdog",
      script: path.join(root, "watchdog.py"),
      cwd: root,
      interpreter: "python3",
      autorestart: true,
      env: { PROJECT_ROOT: root },
    },
    {
      name: "field-monitor",
      script: path.join(root, "field_monitor.py"),
      cwd: root,
      interpreter: "python3",
      autorestart: true,
      env: { PROJECT_ROOT: root },
    },
    {
      name: "debug-controller",
      script: path.join(root, "debug_controller.py"),
      cwd: root,
      interpreter: "python3",
      autorestart: true,
      env: { PROJECT_ROOT: root, DEBUG_HOST: "127.0.0.1" },
    },
  ],
};
