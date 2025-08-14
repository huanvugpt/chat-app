#!/bin/bash
set -e

# Thư mục chứa file key SSH
cd /home/huanvm/Desktop/me/azure

# SSH vào server và chạy các lệnh
ssh -i CHAT_key.pem huanvm@104.214.189.43 << 'EOF'
    cd ~/chat-app
    git reset --hard
    git pull origin main
    pm2 reload ecosystem.config.js --update-env
    pm2 save
EOF

echo "✅ Deploy completed!"
