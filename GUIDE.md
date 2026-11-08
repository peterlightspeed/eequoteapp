# EE Solutions Quotes: Deploy Guide (Supabase or Neon + Render + Vercel)

**Version 2.** New EE quote template, any-currency quotes, redesigned screens with the EE logo, optional two-step sign-in, stronger security.
Cloud only: the **database** on Supabase *or* Neon (use one), the **backend** on Render, the **screens** on Vercel (optional).

---

## 1. What changed in this version

| Area | What you get |
|---|---|
| **Quote PDF** | EE's real template: logo, RC, office and training-centre addresses, client grid, `<PRODUCT> QUOTE` bar, DURATION column, TOTAL / VAT / TOTAL BUY PRICE, **amount in words**, terms, logo bottom right. Typos fixed ("SOFTWARE KIT UNIT", "corporate"). |
| **Currencies** | Distributor prices can be in **NGN, USD, EUR, GBP, ZAR, GHS, KES, CAD, AED**. The customer quote can be in any of them. The margin is applied in the distributor's currency, then converted with an **editable rate**. NGN to NGN needs no rate. |
| **Screens** | Branded sign-in, drag-and-drop PDF upload, live totals panel, margin slider, step tracker, PDF **preview**, saved-quote search, admin and activity log, works on phones, dark mode. |
| **Security** | Optional **two-step sign-in** (authenticator app), per-IP rate limits, strict browser security headers, no data in URLs, idle sign-out, activity log, safer errors. |
| **Details** | Reference like `INV/EESOL/20261104_2603`, editable prepared-by and terms, date `4TH NOV., 2026`. |

### About "blocking inspect": what is and isn't possible
Anything the browser shows (the page's code, the API address, the data on screen) **can always be seen** by the person using that browser. Blocking F12 or right-click is easy to get around and only annoys honest staff, so it is **not** in the app. What actually protects you, and is built in:
- **Every API call needs a login**; the server checks it, not the page. Without an account, the API returns nothing.
- **No secrets in the front end** (no keys, no database address), and no third-party scripts, fonts or analytics.
- **Nothing sensitive in URLs.** Tokens travel in a header, never in the address, so nothing leaks via history, logs or the Referer header (`Referrer-Policy: no-referrer`).
- **Search engines are told to stay away** (`noindex`, `robots.txt`).
- **Strict Content-Security-Policy**, so injected scripts cannot run or send data elsewhere.
- **Generic errors**, no stack traces, and the server never echoes back what you typed (passwords included).
- With Vercel, the browser only talks to the **Vercel address**; the Render address stays behind it.
- **Two-step sign-in** and the **activity log** for when passwords alone are not enough.

---

## 2. Update your project: unzip, combine, push

Your project is in `~/ee-quote-app`. Your `.env`, `local.db` and `.venv` are **not** in the new zip, so they stay untouched.

```bash
cd ~
# 1. unzip the new version into a temporary folder (adjust the zip name/path)
unzip -o ~/Downloads/ee-quote-app-v2.zip -d ~/ee-quote-v2

# 2. combine: copy everything over your project, hidden files included
cp -a ~/ee-quote-v2/ee-quote-app/. ~/ee-quote-app/
rm -rf ~/ee-quote-v2
cd ~/ee-quote-app

# 3. remove the old on-prem files if you still have them from version 1 (safe to run even if they are gone)
git rm -r -q --ignore-unmatch Dockerfile docker-compose.yml Caddyfile scripts ONPREM.md .dockerignore .gitattributes
rm -rf Dockerfile docker-compose.yml Caddyfile scripts ONPREM.md .dockerignore .gitattributes

# 4. SAFETY CHECK: must print OK
git ls-files | grep -E '(^|/)\.env$|\.db$|\.venv/' && echo "STOP: secrets tracked" || echo "OK"
```

**Already pushed before** (the repo exists on GitHub):
```bash
cd ~/ee-quote-app
git add -A
git status --short | head -50
git commit -m "v2: EE quote template, multi-currency, new UI, 2-step sign-in, security"
git push
```

**First push ever** (create an empty **Private** repo `ee-quote-app` on github.com first, no README):
```bash
cd ~/ee-quote-app
git config --global user.name "Peter Eluwade"
git config --global user.email "your-email@example.com"
git init -b main
git add -A
git commit -m "EE Solutions quote automation v2"
git remote add origin git@github.com:<YOUR-GITHUB-USERNAME>/ee-quote-app.git
git push -u origin main
```
(No SSH key yet? `ssh-keygen -t ed25519 -C "peter" -f ~/.ssh/id_ed25519 -N ""`, then `cat ~/.ssh/id_ed25519.pub` and add it on GitHub under Settings > SSH and GPG keys. Test with `ssh -T git@github.com`. Turn on 2FA for your GitHub account.)

---

## 3. Test on your computer first

```bash
cd ~/ee-quote-app/backend
source .venv/bin/activate
pip install -r requirements.txt        # new: Pillow
python -m pytest -q                    # optional: pip install -r requirements-dev.txt first
uvicorn app.main:app --reload --port 8000
```
Open http://127.0.0.1:8000, press **Ctrl+Shift+R**, sign in. Your old `local.db` is upgraded automatically on start-up (new columns are added; old quotes still open and download).

Try this: upload `samples/distributor_invoice_sample.pdf` → type a client → Preview → Download. Compare with `samples/ee_quote_template.pdf`.

---

## 4. Deploy

Order: **Supabase** (database) → **Render** (backend) → **Vercel** (front end, optional) → first login.

### 4.1 Database: pick ONE, Supabase or Neon
Both are free to start and both work with this app. The app creates its own tables on first start, so `schema.sql` is only needed for the Supabase security step.

**Option A: Supabase**
1. supabase.com → **New project** → name `ee-quotes` → choose the region closest to Nigeria that is offered → set a **database password using letters and digits only** (avoids URL-encoding problems). Save it.
2. **SQL Editor** → paste all of `schema.sql` → **Run**. This creates the tables and switches on Row Level Security with no policies, so Supabase's public API cannot read them.
3. Click **Connect** (top of the project) → copy the **Session pooler** connection string (IPv4). It looks like:
   `postgresql://postgres.<project-ref>:<YOUR-PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   Replace `<YOUR-PASSWORD>` with your password. This is your `DATABASE_URL`.

**Option B: Neon**
1. neon.tech → sign up → **Create project** → name `ee-quotes` → choose the region closest to you → create.
2. On the project dashboard click **Connect** (or **Connection details**), tick **Pooled connection**, and copy the connection string. It looks like:
   `postgresql://<user>:<password>@ep-xxxx-pooler.<region>.aws.neon.tech/<dbname>?sslmode=require`
   This is your `DATABASE_URL`. If you see `&channel_binding=require` at the end and the app fails to connect, delete that part.
3. Nothing else to run: the app creates its tables on first start. (Neon does not expose a public data API, so there is no Row Level Security step.)
4. Neon's free database goes to sleep when idle and wakes in about a second on the next request; the first request after a quiet period can be a bit slower.

Switching later: export with `pg_dump`, import into the new database with `psql`, and change `DATABASE_URL` on Render.

### 4.2 Render (backend)
1. render.com → sign in with GitHub → **New +** → **Web Service** → pick the `ee-quote-app` repo.
2. Settings:

| Field | Value |
|---|---|
| Name | `ee-quotes` (your URL becomes `https://ee-quotes.onrender.com`; if taken, Render adds letters) |
| Region | the closest to Nigeria that is offered (for example Frankfurt) |
| Branch | `main` |
| Runtime | `Python 3` |
| Build Command | `pip install -r backend/requirements.txt` |
| Start Command | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*' --no-server-header` |
| Health Check Path | `/health` |
| Instance Type | `Free` |

(Or use **New + > Blueprint**; it reads `render.yaml` and asks for the secret values.)

3. **Environment** tab → add these (generate secrets in your terminal: `python3 -c "import secrets;print(secrets.token_hex(32))"`):

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.3` |
| `APP_ENV` | `production` |
| `ENABLE_DOCS` | `false` |
| `DATABASE_URL` | the Supabase Session pooler string **or** the Neon pooled string |
| `JWT_SECRET` | the 64-character random string you generated |
| `ALLOWED_HOSTS` | first deploy: `*.onrender.com`; after Vercel is ready: `ee-quotes.onrender.com,ee-quotes.vercel.app` (your real two addresses) |
| `SUPERADMIN_EMAIL` | your email |
| `SUPERADMIN_PASSWORD` | a strong first password (10+ characters, letters and numbers; you will change it) |
| `AUTHORIZED_BY` | `Babajide Padonu` |
| `COMPANY_NAME` | `EE Solutions Limited` |

   Optional: `PREPARED_BY`, `PREPARED_ROLE`, `PREPARED_EMAIL`, `PREPARED_PHONE`, `QUOTE_VALID_DAYS` (default 15), `REF_PREFIX` (default `INV/EESOL`), `REF_SEQ_START` (default 1), `ROUND_LINES` (`false` = same as Dami's Excel), `QUOTE_PAGE` (`A4` or `LETTER`), `MAX_LOGIN_ATTEMPTS` (3), `LOGIN_RATE_PER_MIN` (10).

4. **Create Web Service**. The first build takes a few minutes. Open `https://<your-service>.onrender.com/health`. It should show `{"ok":true}`. Then open the Render address itself: it already serves the app, so **you can stop here** if you don't want Vercel.

### 4.3 Vercel (front end, optional)
Vercel serves the screens and passes `/api/...` calls to Render, so people only ever see the Vercel address.

1. Open `frontend/vercel.json` and replace `YOUR-RENDER-APP.onrender.com` with your real Render address (no `https://`, no slash at the end). Commit and push:
   ```bash
   cd ~/ee-quote-app
   git add frontend/vercel.json && git commit -m "Point Vercel at Render" && git push
   ```
2. vercel.com → sign in with GitHub → **Add New… > Project** → import `ee-quote-app`.
3. **Root Directory: `frontend`** (click Edit and pick the folder). **Framework Preset: Other.** Leave Build Command and Output Directory empty. **Deploy**.
4. **Environment variables on Vercel: none are needed.** The Render address lives in `vercel.json`, so nothing is stored in the browser or in Vercel settings.
5. Copy your Vercel address (for example `ee-quotes.vercel.app`) and update Render's `ALLOWED_HOSTS` to the exact two hosts (section 4.2), then let Render redeploy.
6. Open the Vercel address and sign in.

Good to know: a PDF upload that goes through Vercel can be limited to about 4.5 MB (as far as I know). Larger PDFs: use the Render address.

### 4.4 First login and lock-down
1. Sign in with `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD`.
2. **Account → Change my password** (use a new strong one).
3. **Account → Two-step sign-in → Turn on.** In Google/Microsoft Authenticator choose *Enter a setup key* (account `EE Solutions`, type *time based*), type the 6-digit code, **Confirm**.
4. On Render, **delete** the `SUPERADMIN_PASSWORD` variable (it's only needed once) and save.
5. **Admin → Add a user**: add Dami and Olamide as **Admin**, staff as **Staff**; ask admins to turn on two-step too.

### 4.5 Keep it awake and backed up
- **UptimeRobot** (free): New monitor → HTTP(s) → `https://<your-service>.onrender.com/health` → every 5 minutes. The free Render service sleeps after about 15 minutes idle, and `/health` also keeps Supabase active.
- **Backups:** I'm not certain either free plan keeps long backup history, so check their current terms. Make your own weekly copy (use the same address as your `DATABASE_URL`, without the `+psycopg2` part):
  ```bash
  sudo apt install -y postgresql-client
  mkdir -p ~/ee-backups
  pg_dump "<YOUR-DATABASE-URL>" | gzip > ~/ee-backups/eequotes_$(date +%F).sql.gz
  ```
  Store those files somewhere safe (not only on the same laptop).

### 4.6 Updating later
```bash
cd ~/ee-quote-app && git add -A && git commit -m "what changed" && git push
```
Render and Vercel redeploy by themselves. Check Render **Logs** if something looks wrong.

---

## 5. Using the app (staff)
1. **Distributor quote:** drop the PDF (or add lines by hand). Choose the **distributor's currency**. If the PDF clearly uses another currency the app switches it and tells you.
2. **Pricing:** choose the **customer's currency**, check the **rate** (`1 USD = 1,400 NGN`; type your own, or press *use it* for today's market rate), set the **margin** (slider, chips or typing), and set a different margin on one line if needed (for example services). **Professional services** adds the standard line. *Customer budget* + **Fit** works out the margin for you.
3. **Client & details:** product (prints as `MORPHISEC QUOTE`), date, reference (automatic), company, client, position, address, prepared-by (remembered on this computer), terms.
4. **Review:** **Preview** or **Download quote**. The quote is saved automatically; change something and download again and the same quote is updated. **Saved quotes** has search, download, **Reuse** and (admins) delete.

Rates: `NGN` is treated as the "weak" side, so a EUR-to-NGN quote shows `1 EUR = ₦…`. If the distributor is in NGN and the customer wants USD, you still type `1 USD = ₦…`. The app converts the right way round.

---

## 6. Security checklist
- [ ] Private GitHub repo, 2FA on GitHub, `.env` never committed (section 2 check)
- [ ] `APP_ENV=production`, `ENABLE_DOCS=false`, `ALLOWED_HOSTS` set to the exact addresses
- [ ] `JWT_SECRET` is random and 32+ characters; `SUPERADMIN_PASSWORD` removed from Render after first login
- [ ] Two-step sign-in on for every admin (and ideally everyone)
- [ ] Everyone has their own account; remove leavers (Admin → delete)
- [ ] Database: Supabase Row Level Security ON (`schema.sql`) or Neon; database password never shared
- [ ] Look at the **activity log** weekly for repeated failed or locked logins
- [ ] Weekly backup copy stored somewhere else

**Honest limits.** The lock after 3 wrong passwords shows that an email exists once someone has failed 3 times on it. Per-IP limits slow guessing but cannot stop a determined attacker. Your data lives with your database provider (Supabase or Neon) and Render; their staff can technically reach it, so keep the accounts on those services protected with strong passwords and 2FA.

---

## 7. Environment reference

| Variable | Default | Meaning |
|---|---|---|
| `APP_ENV` | `development` | `production` turns on the safety checks |
| `DATABASE_URL` | `sqlite:///./local.db` | database |
| `JWT_SECRET` | none | 32+ random characters (required in production) |
| `JWT_HOURS` | `8` | login lifetime (also signs out after 30 min idle) |
| `ALLOWED_HOSTS` | `*` | addresses the app answers to (required in production) |
| `ENABLE_DOCS` | `true` dev / `false` prod | API documentation page |
| `MAX_LOGIN_ATTEMPTS` / `LOGIN_RATE_PER_MIN` / `GENERAL_RATE_PER_MIN` / `MIN_PASSWORD_LEN` | `3` / `10` / `240` / `10` | lock, sign-in limit, API limit, password length |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | none | first account; delete the password after first login |
| `DEFAULT_MARGIN` / `DEFAULT_VAT` / `DEFAULT_FX` | `0.20` / `0.075` / `1400` | first-run defaults (edit in the app afterwards) |
| `ROUND_LINES` | `false` | `true` rounds each line to cents |
| `REF_PREFIX` / `REF_SEQ_START` | `INV/EESOL` / `1` | reference `INV/EESOL/20261104_0001` |
| `QUOTE_VALID_DAYS` / `QUOTE_PAGE` | `15` / `A4` | terms text, paper (`LETTER` matches the Excel sheet) |
| `COMPANY_NAME`, `COMPANY_RC`, `COMPANY_ADDRESS`, `OFFICE_ADDRESS`, `TRAINING_ADDRESS`, `COMPANY_TAGLINE` | EE's real details | printed header (`\|` = new line) |
| `AUTHORIZED_BY`, `PREPARED_BY/ROLE/EMAIL/PHONE` | `Babajide Padonu`, blank | defaults in the form |

**Vercel:** no environment variables.

---

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| Render deploy fails with "Unsafe production configuration" | read the lines in the log: set `JWT_SECRET` (32+ chars) and `ALLOWED_HOSTS` |
| "Invalid host header" | the address you typed is not in `ALLOWED_HOSTS` (add both the Render and Vercel addresses) |
| Vercel page loads but sign-in says "Cannot reach the server" | `frontend/vercel.json` still says `YOUR-RENDER-APP`; fix, push, redeploy |
| First request is slow | free Render service (and Neon) waking up; use UptimeRobot on `/health` |
| Database error `connection refused` / IPv6 (Supabase) | use the **Session pooler** string, not "Direct connection" |
| Neon: `channel binding` or SSL error | keep `?sslmode=require` and delete `&channel_binding=require` |
| `password authentication failed` | wrong database password in `DATABASE_URL` |
| Preview is blank | your browser blocked the built-in viewer: use **Open in new tab** or **Download** |
| PDF upload says "scan" or finds no lines | add lines by hand; send me that PDF so the reader can learn it |
| Locked out | another admin unlocks (Admin tab). All admins locked: on Render run `python unlock_cli.py email` in the **Shell** tab (inside `backend`) |
| Lost the authenticator phone | an admin uses **Admin → Reset 2-step**; the super admin resets admins |

---

## 9. Questions for Dami
1. **Reference number.** `INV/EESOL/20261104_2603`: is **2603** a running number? The app uses (number of saved quotes + `REF_SEQ_START`). What number should it start from? Should a *quote* really start with `INV`?
2. **Authorized by:** always Babajide Padonu? **Prepared-by** details are typed per person and remembered.
3. **Terms.** Are the 4 default terms right (VAT 7.5%, coverage period stated, bank transfer, valid 15 days)? Should bank account details be printed?
4. **Paper size.** The Excel template is *Letter*; the app prints **A4 landscape** by default. Which one do you print?
5. **Duration.** Imported lines are pre-filled with "12 months" and services are blank. OK?
6. **Corrections made** to the template text: "SOFTWAKE" to "SOFTWARE", "coporate" to "corporate". OK?
7. **Amount in words.** With no kobo it ends "naira only". OK?
8. **Product title** ("MORPHISEC QUOTE"): is this always the vendor name?
9. Still open from before: professional-services margin (50% markup?), VAT-exempt lines, which exchange-rate source she uses, the distributors' names plus one real PDF from each, and the list of staff emails and admins.
