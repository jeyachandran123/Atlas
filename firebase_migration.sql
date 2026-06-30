-- Firebase Authentication Migration
-- Run this manually if alembic fails

-- Add Firebase OAuth fields to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(20) DEFAULT 'email';
ALTER TABLE users ADD COLUMN IF NOT EXISTS firebase_uid VARCHAR(255) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture_url VARCHAR(500);

-- Update existing password field to allow empty string
ALTER TABLE users ALTER COLUMN hashed_password SET DEFAULT '';

-- Create index on firebase_uid
CREATE INDEX IF NOT EXISTS ix_users_firebase_uid ON users(firebase_uid);

-- Show success message
SELECT 'Firebase authentication fields added successfully!' AS status;
