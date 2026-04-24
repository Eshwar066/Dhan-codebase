# Trading Web UI Deployment (SolidJS + DaisyUI + FastAPI)

## 1) Build and install UI

```bash
cd /root/Dhan-codebase/ui
npm install
npm run build
sudo mkdir -p /var/www/trader-ui
sudo rsync -a dist/ /var/www/trader-ui/
```

## 2) Install API dependencies and run service

```bash
cd /root/Dhan-codebase
source .venv/bin/activate
pip install -r requirements.txt
sudo cp systemd/trader-control-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable trader-control-api
sudo systemctl start trader-control-api
sudo systemctl status trader-control-api
```

## 3) Configure Nginx

```bash
sudo cp deploy/nginx/trader.conf /etc/nginx/sites-available/trader.conf
sudo ln -s /etc/nginx/sites-available/trader.conf /etc/nginx/sites-enabled/trader.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 4) TLS certificate (Let's Encrypt)

```bash
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d trader.yourdomain.com
```

## 5) DNS

Create an `A` record:

- `trader.yourdomain.com` -> your droplet public IP

## 6) URLs

- UI: `https://trader.yourdomain.com`
- API health: `https://trader.yourdomain.com/api/health`
- WebSocket: `wss://trader.yourdomain.com/ws/events`

## Notes

- API writes operator runtime state to `logs/runtime_state.json`.
- Current control endpoints persist operator intent (`start/stop/restart`, strategy toggles/additions).
- Hook process-level engine orchestration into `POST /api/engines/{engine_id}/action` if you want fully automated start/stop from UI.

