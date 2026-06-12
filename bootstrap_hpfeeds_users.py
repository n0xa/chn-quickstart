#!/usr/bin/env python3
"""
Bootstrap script to provision hpfeeds users from environment files.
This should be run after docker-compose up to ensure all hpfeeds clients
can authenticate with the hpfeeds3 broker.
"""

import os
import subprocess
import time
import sys


def parse_env_file(filepath):
    """Parse environment file and extract hpfeeds credentials."""
    if not os.path.exists(filepath):
        return None
    
    env_vars = {}
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    
    # Extract hpfeeds credentials
    ident = env_vars.get('HPFEEDS_IDENT')
    secret = env_vars.get('HPFEEDS_SECRET')
    channels = env_vars.get('HPFEEDS_CHANNELS', '')
    
    if ident and secret:
        return {
            'ident': ident,
            'secret': secret,
            'channels': [c.strip() for c in channels.split(',') if c.strip()]
        }
    return None


def provision_user_via_docker(user_data, is_publisher=False):
    """Provision a user in the hpfeeds3 MongoDB database via docker exec."""
    
    # Prepare MongoDB command
    channels_array = "['" + "','".join(user_data['channels']) + "']" if user_data['channels'] else "[]"
    
    mongo_cmd = f'''
    use hpfeeds3;
    db.authkey.replaceOne(
        {{_id: "{user_data['ident']}"}},
        {{
            _id: "{user_data['ident']}",
            secret: "{user_data['secret']}",
            pubchans: {channels_array if is_publisher else "[]"},
            subchans: {channels_array if not is_publisher else "[]"}
        }},
        {{upsert: true}}
    );
    '''
    
    try:
        result = subprocess.run([
            'docker', 'exec', 'chn-quickstart-mongodb-1', 
            'mongosh', '--eval', mongo_cmd
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"✅ Provisioned user: {user_data['ident']}")
            return True
        else:
            print(f"❌ Failed to provision user {user_data['ident']}: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Failed to provision user {user_data['ident']}: {e}")
        return False


def wait_for_mongodb():
    """Wait for MongoDB to be ready."""
    print("⏳ Waiting for MongoDB to be ready...")
    max_retries = 30
    
    for attempt in range(max_retries):
        try:
            result = subprocess.run([
                'docker', 'exec', 'chn-quickstart-mongodb-1', 
                'mongosh', '--eval', 'db.adminCommand("ping")'
            ], capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                print("✅ MongoDB is ready")
                return True
        except Exception:
            pass
        
        if attempt < max_retries - 1:
            print(f"⏳ Waiting for MongoDB... ({attempt + 1}/{max_retries})")
            time.sleep(2)
    
    print(f"❌ MongoDB not available after {max_retries} attempts")
    return False


def main():
    """Main bootstrap function."""
    print("🚀 Bootstrapping hpfeeds users...")
    
    # Check if docker is available
    try:
        subprocess.run(['docker', '--version'], capture_output=True, timeout=5)
    except Exception:
        print("❌ Docker is not available. Please ensure Docker is installed and running.")
        sys.exit(1)
    
    # Check if MongoDB container is running
    try:
        result = subprocess.run([
            'docker', 'ps', '--filter', 'name=chn-quickstart-mongodb-1', '--format', '{{.Names}}'
        ], capture_output=True, text=True, timeout=5)
        
        if 'chn-quickstart-mongodb-1' not in result.stdout:
            print("❌ MongoDB container is not running. Please run 'docker-compose up -d' first.")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error checking Docker containers: {e}")
        sys.exit(1)
    
    # Wait for MongoDB to be ready
    if not wait_for_mongodb():
        sys.exit(1)
    
    # Service configurations
    services = [
        {
            'name': 'mnemosyne',
            'env_file': 'config/sysconfig/mnemosyne.env',
            'is_publisher': False  # mnemosyne only subscribes
        }
    ]
    
    # Check for other hpfeeds services
    for env_file in ['config/sysconfig/hpfeeds-cif.env', 'config/sysconfig/hpfeeds-logger.env']:
        if os.path.exists(env_file):
            service_name = os.path.basename(env_file).replace('.env', '')
            services.append({
                'name': service_name,
                'env_file': env_file,
                'is_publisher': False  # these are typically subscribers too
            })
    
    # Provision users
    success_count = 0
    for service in services:
        print(f"\n📋 Processing {service['name']}...")
        
        user_data = parse_env_file(service['env_file'])
        if user_data:
            if provision_user_via_docker(user_data, service['is_publisher']):
                success_count += 1
        else:
            print(f"⚠️  No valid hpfeeds credentials found in {service['env_file']}")
    
    print(f"\n🎉 Bootstrap complete! Provisioned {success_count}/{len(services)} users")
    
    if success_count == 0:
        print("⚠️  No users were provisioned. Check your environment files.")
        sys.exit(1)
    
    # Restart mnemosyne to pick up the new credentials
    if success_count > 0:
        print("\n🔄 Restarting mnemosyne to apply new credentials...")
        try:
            subprocess.run(['docker', 'restart', 'chn-quickstart-mnemosyne-1'], 
                         capture_output=True, timeout=30)
            print("✅ Mnemosyne restarted successfully")
        except Exception as e:
            print(f"⚠️  Could not restart mnemosyne: {e}")


if __name__ == '__main__':
    main()