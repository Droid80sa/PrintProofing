#!/bin/bash

# Set up Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r app/requirements.txt

# Create default .env file if it doesn't exist
if [ ! -f .env ]; then
  cat <<EOT >> .env
MAIL_SERVER=smtp.example.com
MAIL_PORT=465
MAIL_USE_SSL=true
MAIL_USERNAME=you@example.com
MAIL_PASSWORD=yourpassword
MAIL_DEFAULT_SENDER=you@example.com
MAIL_DEFAULT_REPLY_TO=you@example.com
# Base URL for proof links, e.g. https://proof.example.com
PUBLIC_BASE_URL=
FILE_BASE_URL=
FILE_STORAGE_ROOT=/mnt/proofs
FILE_STORAGE_BACKEND=local
AWS_S3_BUCKET=
AWS_S3_PREFIX=proofs
AWS_S3_REGION=
AWS_S3_ENDPOINT_URL=
SECRET_KEY=thisisasecret
# PostgreSQL connection string (Docker Compose default uses host `db`)
DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/proofs_app
EOT
  echo ".env file created with defaults."
else
  echo ".env file already exists."
fi

echo "Setup complete. You can now run the app with: docker compose up"
