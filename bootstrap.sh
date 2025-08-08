#!/bin/bash
set -e

echo "🚀 CHN Bootstrap Script"
echo "======================="

# Check if docker-compose is running
if ! docker ps | grep -q "chn-quickstart"; then
    echo "❌ CHN stack is not running. Please run 'docker-compose up -d' first."
    exit 1
fi

echo "✅ CHN stack is running"

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Bootstrap hpfeeds users
echo "🔧 Provisioning hpfeeds users..."
python3 bootstrap_hpfeeds_users.py

echo ""
echo "🎉 Bootstrap complete!"
echo ""
echo "Next steps:"
echo "1. Check CHN dashboard at http://localhost"
echo "2. Deploy honeypots using the generated deploy keys"
echo "3. Monitor attack data flowing into the system"