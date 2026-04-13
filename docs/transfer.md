# Transferring and Deploying to an Ubuntu VM

This guide provides step-by-step instructions for transferring your application (frontend and backend) to an Ubuntu Virtual Machine and running the backend robustly using Gunicorn managed by a Systemd service, alongside Nginx acting as a reverse proxy.

## 1. Prerequisites
- An Ubuntu VM with SSH access.
- A user account with `sudo` privileges.
- Your project directory (`submission2`) on your local machine.

## 2. Transferring Files to the VM

We'll use `rsync` from your local machine to securely copy the files to the VM. 

Open a terminal on your local machine and run:

```bash
# Define your VM's IP address and your username on the VM
VM_USER="ubuntu"
VM_IP="your_vm_ip_address"

# Sync the directory to the VM (this excludes pycache and existing venvs)
rsync -avz --exclude='__pycache__' --exclude='venv' --exclude='.git' /Users/aditya/temp/vm/submission2/ ${VM_USER}@${VM_IP}:~/submission2
```

## 3. Server Setup (On the Ubuntu VM)

SSH into your Ubuntu VM:
```bash
ssh ${VM_USER}@${VM_IP}
```

Once logged in, install the necessary system dependencies:

```bash
# Update package lists
sudo apt update

# Install Python 3, pip, virtualenv, Nginx, and UFW (firewall)
sudo apt install -y python3 python3-pip python3-venv nginx ufw
```

## 4. Setting up the Python Environment

Navigate to your project directory and set up a virtual environment to isolate the Python dependencies:

```bash
cd ~/submission2

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install the required packages, including Gunicorn
pip install -r docs/requirements.txt
pip install gunicorn
```

Check that Gunicorn can run your app locally (optional, for testing):
```bash
# Verify Gunicorn starts correctly with your application's entry point
# We use --chdir to set the correct python path for the internal imports.
gunicorn --chdir backend/api --bind 0.0.0.0:8000 wsgi:application
```
*(Press `Ctrl+C` to exit after confirming it starts successfully).*

## 5. Setting up Gunicorn as a Systemd Service

We want Gunicorn to run continuously in the background and start automatically when the server reboots. We will create a `systemd` service file for this.

Create a new service file:
```bash
sudo nano /etc/systemd/system/submission2-api.service
```

Add the following configuration (replace `ubuntu` with your actual Linux user if different):

```ini
[Unit]
Description=Gunicorn instance to serve the Submission2 API
After=network.target

[Service]
# The user and group that the process will run under
User=ubuntu
Group=www-data

# Set the working directory to where your backend application is
WorkingDirectory=/home/ubuntu/submission2

# Set the PATH so it uses the virtual environment's binaries
Environment="PATH=/home/ubuntu/submission2/venv/bin"

# The command to start Gunicorn
# Use --chdir so it resolves imports correctly, and wsgi:application as the entry point
ExecStart=/home/ubuntu/submission2/venv/bin/gunicorn --chdir /home/ubuntu/submission2/backend/api --workers 3 --bind unix:/home/ubuntu/submission2/submission2-api.sock -m 007 wsgi:application

[Install]
WantedBy=multi-user.target
```

**Start and Enable the Service:**

```bash
# Reload changes to systemd
sudo systemctl daemon-reload

# Start the Gunicorn service
sudo systemctl start submission2-api

# Enable it to start on boot
sudo systemctl enable submission2-api

# Check the status to ensure it's running without errors
sudo systemctl status submission2-api
```

## 6. Configuring Nginx

Now configure Nginx to proxy API requests to Gunicorn (via the Unix socket) and serve the static frontend files.

If you have a global Nginx config file locally (`backend/nginx.conf`), you could copy its contents. Otherwise, create a standard site configuration natively on the VM:

```bash
sudo nano /etc/nginx/sites-available/submission2
```

Add the following configuration:

```nginx
server {
    listen 80;
    server_name your_domain_or_IP;

    # Proxy API requests to Gunicorn
    location /api/ {
        include proxy_params;
        proxy_pass http://unix:/home/ubuntu/submission2/submission2-api.sock;
    }

    # Serve the frontend static files
    location / {
        root /home/ubuntu/submission2/frontend/public;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
}
```

Enable the configuration and restart Nginx:

```bash
# Remove the default site configuration
sudo rm /etc/nginx/sites-enabled/default

# Symlink to enable the new site
sudo ln -s /etc/nginx/sites-available/submission2 /etc/nginx/sites-enabled

# Test the Nginx configuration for syntax errors
sudo nginx -t

# Restart Nginx to apply changes
sudo systemctl restart nginx
```

## 7. Firewall (UFW) Configuration 

Configure standard network firewall rules:

```bash
# Allow ssh, http, and https traffic
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'

# Enable the firewall
sudo ufw enable
```

## 8. Troubleshooting

- **Permissions**: Make sure the `/home/ubuntu/submission2` directory has appropriate executing permissions so the `www-data` group can access it. Run: `chmod +x /home/ubuntu`
- **Checking Gunicorn Logs**: If the API isn't responding, check the service logs:
  ```bash
  sudo journalctl -u submission2-api -f
  ```
- **Checking Nginx Logs**: If you get a 502 Bad Gateway or 404 error, check Nginx logs:
  ```bash
  sudo tail -f /var/log/nginx/error.log
  sudo tail -f /var/log/nginx/access.log
  ```
