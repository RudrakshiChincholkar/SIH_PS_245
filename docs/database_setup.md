# PostgreSQL Database Setup Guide

This document describes how to install, configure, and verify PostgreSQL for the AI-based Attendance Monitoring System.

---

## 1. Prerequisites & Service Check

Check whether PostgreSQL is installed and accepting connections:

```bash
# Check if PostgreSQL service is running
systemctl status postgresql

# Check if PostgreSQL is accepting connections on port 5432
pg_isready -h localhost -p 5432
```

If PostgreSQL is not installed on Ubuntu/Debian:
```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

---

## 2. Dedicated Least-Privilege User & Database Setup

For security, the application **must not** run under the administrative `postgres` superuser. Follow these steps to create a dedicated user and database:

### Step 1: Open `psql` as administrator
```bash
sudo -u postgres psql
# Or if you have a password set on the postgres user:
psql -h localhost -U postgres
```

### Step 2: Execute Database & User Creation SQL
```sql
-- 1. Create dedicated application user
CREATE ROLE sih_user WITH LOGIN PASSWORD 'sih_secure_pass_2026';

-- 2. Create dedicated database owned by sih_user
CREATE DATABASE sih_attendance OWNER sih_user;

-- 3. Grant privileges
GRANT ALL PRIVILEGES ON DATABASE sih_attendance TO sih_user;

-- 4. Switch to sih_attendance and grant schema privileges
\c sih_attendance
GRANT ALL ON SCHEMA public TO sih_user;
```

---

## 3. Verify Connection

Verify that `sih_user` can connect to `sih_attendance`:

```bash
PGPASSWORD='sih_secure_pass_2026' psql -h localhost -U sih_user -d sih_attendance -c "SELECT current_user, current_database(), version();"
```

Expected output:
```
 current_user | current_database | version
--------------+------------------+-----------------------------
 sih_user     | sih_attendance   | PostgreSQL 14.x on ...
(1 row)
```

---

## 4. Configure Backend Environment

Copy `.env.example` to `.env` in the `backend/` directory:

```bash
cd backend
cp .env.example .env
```

Ensure the database variables in `backend/.env` match your PostgreSQL credentials:

```env
DB_HOST="localhost"
DB_PORT=5432
DB_USER="sih_user"
DB_PASSWORD="sih_secure_pass_2026"
DB_NAME="sih_attendance"
```

> **Security Reminder**: Never commit `backend/.env` to source control. It is already ignored in `.gitignore`.

---

## 5. Troubleshooting Common Issues

### Issue 1: `Connection refused (errno 111)`
- **Cause**: PostgreSQL service is stopped or listening on a different port.
- **Fix**: Run `sudo systemctl start postgresql` and check `netstat -tlpn | grep 5432`.

### Issue 2: `FATAL: password authentication failed for user "sih_user"`
- **Cause**: Incorrect password or pg_hba.conf is rejecting password authentication.
- **Fix**: Reset user password via admin `psql`: `ALTER USER sih_user WITH PASSWORD 'sih_secure_pass_2026';` and verify `md5` or `scram-sha-256` is enabled in `/etc/postgresql/<version>/main/pg_hba.conf`.

### Issue 3: `FATAL: database "sih_attendance" does not exist`
- **Fix**: Re-run the `CREATE DATABASE sih_attendance OWNER sih_user;` command as the postgres superuser.

---

## 6. Isolated Test Database (`sih_attendance_test`)

An isolated test database is configured to ensure automated tests run safely without corrupting production or development records:

```sql
-- Create isolated test database owned by sih_user
CREATE DATABASE sih_attendance_test OWNER sih_user;
GRANT ALL PRIVILEGES ON DATABASE sih_attendance_test TO sih_user;
\c sih_attendance_test
GRANT ALL ON SCHEMA public TO sih_user;
```

In `backend/.env`:
```env
TEST_DB_NAME="sih_attendance_test"
```
Tests automatically read this configuration without exposing credentials on the command line.
