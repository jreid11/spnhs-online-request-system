# Deploy SPNHS-SHS Online Request System to Vercel + Neon

## What you need

- A GitHub account
- A Vercel account
- A Neon account, or the Neon integration available through Vercel Marketplace
- The extracted contents of this project

The repository root must contain `app.py`, `requirements.txt`, `templates/`, `public/`, and `form_templates/`. Do not upload only the outer folder while placing the actual app another level deeper.

## Step 1 — Create the GitHub repository

1. Sign in to GitHub.
2. Create a new private repository, for example `spnhs-online-request-system`.
3. Upload all files inside `spnhs_online_request_system_v5` to the repository root.
4. Confirm that `app.py` is visible at the repository root.

Do not upload `.env`, a database password, or an old SQLite database.

## Step 2 — Create the Vercel project

1. Sign in to Vercel.
2. Select **Add New → Project**.
3. Import the GitHub repository.
4. Leave **Framework Preset** on the detected Python/Flask setting or **Other** if no preset is shown.
5. Leave Build Command and Output Directory empty.

Do not deploy yet if the database environment variable has not been added.

## Step 3 — Create or connect Neon Postgres

### Easier method: Vercel Marketplace integration

1. In Vercel, open the project's **Storage** or **Marketplace** section.
2. Add a Neon Postgres database.
3. Connect it to the project.
4. Confirm that Vercel added a `DATABASE_URL` environment variable.

### Manual method

1. Create a project in the Neon Console.
2. Select **Connect** and copy the pooled connection string.
3. In Vercel, open **Project → Settings → Environment Variables**.
4. Add:

```text
Name: DATABASE_URL
Value: postgresql://...neon.tech/...?...sslmode=require&channel_binding=require
```

Apply it to Production, Preview, and Development when those environments should use the database.

## Step 4 — Add the remaining environment variables

In **Vercel → Project → Settings → Environment Variables**, add:

```text
SECRET_KEY=<long random value>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong initial password>
ADMIN_FULL_NAME=SPNHS-SHS Records Administrator
```

Generate a secret key on a computer with Python:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Use a different value for `SECRET_KEY` and `ADMIN_PASSWORD`.

## Step 5 — Deploy

1. Click **Deploy**, or redeploy after adding the variables.
2. Wait for the build to finish.
3. Open the generated `vercel.app` address.

Vercel detects the Flask `app` object in `app.py`. The first database-backed request creates the tables and initial administrator automatically.

## Step 6 — Verify the deployment

Open:

```text
https://YOUR-PROJECT.vercel.app/health
```

Expected response:

```json
{"database":"connected","status":"ok"}
```

Then test:

1. Submit one COE request.
2. Track the request using its tracking number.
3. Open `/admin/login`.
4. Sign in using the administrator details configured in Vercel.
5. Open the request and generate its PDF.
6. Submit a Form 6 and check the field alignment.
7. Delete only the test requests.

## Step 7 — Change the administrator password

After the first successful login, go to **Admin → Password** and change the initial password.

The `ADMIN_PASSWORD` environment variable is used only to create a missing administrator. It does not overwrite an existing password.

## Updating the website later

Edit or replace files in GitHub and commit the changes. Vercel automatically creates a new deployment.

Database records remain in Neon and are not removed when the website is redeployed.

## Common problems

### Website shows DATABASE_URL is missing

The Neon database has not been connected to the project, or `DATABASE_URL` was added to a different environment. Add it to the environment being deployed and redeploy.

### `/health` shows database unavailable

Check:

- the complete Neon connection string was copied
- the password was not altered
- `sslmode=require` is present
- the Vercel deployment was created after the variable was added
- Neon is connected to the correct Vercel project

### Logo or styles are missing

Confirm these repository paths exist:

```text
public/css/style.css
public/js/app.js
public/img/spnhs_logo.png
```

### Admin password does not match the environment variable

An administrator was already created. Use the password-change page in the admin area. For an empty test database only, deleting and recreating the Neon project would trigger fresh initialization, but do not do that after real requests have been submitted.

### PDF takes too long

The included `vercel.json` allows the Flask function to run for up to 30 seconds. The PDFs are generated in memory and are not written to Vercel storage.
