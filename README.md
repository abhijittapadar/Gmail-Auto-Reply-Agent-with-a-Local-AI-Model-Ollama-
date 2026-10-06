# Gmail Auto-Reply Agent with a Local AI Model (Ollama)

A small Python agent that watches your Gmail inbox and writes automatic replies using an AI model running **locally** through [Ollama](https://ollama.com). No paid AI service, no API fees, and your email text never leaves your computer for AI processing.

```
Gmail inbox ──(Gmail API, polled every 30s)──> Python agent ──(localhost:11434)──> Ollama + local model
                                                    │                                      │
                                                    └──── threaded reply sent via Gmail <──┘
```

## Features

- Polls Gmail through the official Gmail API (OAuth 2.0, no app password needed)
- Generates replies with a local model (default `llama3.2`), fully offline for the AI step
- Replies in the **same thread**, then labels the original `AI-Replied` and marks it read
- **Dry-run mode** (default): prints replies instead of sending
- Sender **allow-list** by address (`ALLOWED_SENDERS`) and by domain (`ALLOWED_DOMAINS`)
- Loop and spam protection: skips `noreply`, mailing lists, bulk mail, Promotions/Social/Forums tabs, your own address, and anything marked `Auto-Submitted`
- Per-sender daily reply limit
- Automated-reply disclosure signature on every message
- Failed AI or send attempts are retried on the next cycle

## Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10/11 (steps below). Linux and macOS also work. |
| Python | 3.10 or newer |
| RAM | 4 GB for a 1B model, 8 GB for the 3B default, 16 GB+ for 7B/8B models |
| Disk | About 5 GB free |
| Accounts | A Gmail account and a (free) Google Cloud project for OAuth credentials |

## Repository contents

| File | Purpose |
|---|---|
| `gmail_auto_reply.py` | The agent |
| `requirements.txt` | Python dependencies |
| `run.ps1.example` | Windows launcher template (copy to `run.ps1`) |
| `.gitignore` | Keeps credentials, tokens and logs out of Git |

> **Never commit `credentials.json`, `token.json`, `run.ps1` or `agent.log`.** Anyone holding `token.json` can read and send mail as you. The included `.gitignore` excludes them.

## Quick start (Windows, PowerShell)

### 1. Install Python

Download Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/) and **tick "Add python.exe to PATH"**. Or: `winget install Python.Python.3.12`.

```powershell
python --version
pip --version
```

### 2. Get the code and set up the environment

```powershell
git clone https://github.com/<your-username>/<your-repo>.git $HOME\gmail-agent
cd $HOME\gmail-agent
python -m venv venv
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The prompt should now start with `(venv)`.

### 3. Install Ollama and a model

1. Download **OllamaSetup.exe** from [ollama.com/download](https://ollama.com/download) and run it. Ollama runs in the system tray and starts at sign-in.
2. Pull a model that fits your RAM:

| RAM | Command | Notes |
|---|---|---|
| 4 GB | `ollama pull llama3.2:1b` | Fast, basic quality |
| 8 GB | `ollama pull llama3.2` | Good default |
| 16 GB+ | `ollama pull qwen2.5:7b` | Better quality, slower |

3. Test it:

```powershell
ollama list
ollama run llama3.2 "Write a two-sentence polite reply thanking someone for their email."
Invoke-RestMethod -Uri http://localhost:11434/api/chat -Method Post -ContentType "application/json" -Body '{"model":"llama3.2","stream":false,"messages":[{"role":"user","content":"Say hello"}]}'
```

You should get a response containing `message`. If the connection is refused, open **Ollama** from the Start menu.

### 4. Set up the Gmail API (one time, free)

Done in a web browser. No credit card or billing is needed. Google renames menus now and then; names below follow the newer *Google Auth Platform* layout.

1. **Create a project.** Go to [console.cloud.google.com](https://console.cloud.google.com), signed in with the Gmail account you want to automate. Open the project picker, choose **New project**, name it `gmail-agent`, click **Create**, and make sure it is selected in the top bar.
2. **Enable the Gmail API.** Menu → **APIs & Services → Library** → search **Gmail API** → **Enable**.
3. **Complete the Branding page.** Open **Google Auth Platform → Branding**. Enter app name (`Gmail Agent`), user support email and developer contact email. Leave logo, domains and policy links empty. Click **Save**. *This must be done before the app can be published.*
4. **Set the audience.** Open **Audience**, choose **External**, and under **Test users** click **Add users** and add your Gmail address.
5. **(Optional) Add the scope.** **Data Access → Add or remove scopes** → add `https://www.googleapis.com/auth/gmail.modify`. This lets the app read, label and send mail. It cannot permanently delete mail.
6. **Create the OAuth client.** Open **Clients → Create client**. Choose **Desktop app** (not "Web application"), name it `gmail-agent-desktop`, click **Create**, then **Download JSON**.
7. **Publish the app.** Open **Audience** and click **Publish app** → **Confirm**. Status becomes **In production**. This stops your login from expiring every 7 days. Google does not require verification for personal use.

### 5. Place the credentials file

Rename the downloaded file (`client_secret_...apps.googleusercontent.com.json`) to exactly `credentials.json` and put it in the project folder next to the script:

```powershell
Get-ChildItem $HOME\Downloads -Filter "client_secret*.json"
Copy-Item "$HOME\Downloads\client_secret_*.json" "$HOME\gmail-agent\credentials.json"
Get-ChildItem $HOME\gmail-agent
```

Windows hides file extensions by default, which can leave the name as `credentials.json.json`. Enable **View → Show → File name extensions** in File Explorer and check.

### 6. First run: authorize Gmail (dry-run)

```powershell
cd $HOME\gmail-agent
.\venv\Scripts\Activate.ps1
$env:DRY_RUN = "true"
$env:ALLOWED_SENDERS = "friend@example.com"
python gmail_auto_reply.py
```

1. A browser window opens. Choose your Google account.
2. On **"Google hasn't verified this app"**, click **Advanced → Go to Gmail Agent (unsafe)**. It is your own app.
3. Tick the permission checkbox and click **Continue**.
4. The terminal prints `Authorized as you@gmail.com | model=llama3.2 | dry_run=True` and a `token.json` file is created.

Send a test email **from a different account** (listed in `ALLOWED_SENDERS`) to your Gmail. Within about 30 seconds you should see `[DRY RUN] Would reply to ...` with the generated text. Stop with **Ctrl+C**.

> Mail you send from the monitored account to itself is ignored ("from self"). Always test from a second account.

### 7. Go live

Copy the launcher template and edit it:

```powershell
Copy-Item run.ps1.example run.ps1
notepad run.ps1
```

Set your allow-list and prompt, change `$env:DRY_RUN` to `"false"`, then run:

```powershell
.\run.ps1
```

Send another test email. You should get a threaded reply, and the original message is labeled `AI-Replied` and marked read. Press **Ctrl+C** (possibly twice, because of the restart loop) to stop.

### 8. Run automatically in the background (Task Scheduler)

1. Open **Task Scheduler → Create Task...** (not *Basic Task*).
2. **General:** name `GmailAgent`, *Run only when user is logged on*.
3. **Triggers → New:** *At log on*, optionally *Delay task for 1 minute* so Ollama starts first.
4. **Actions → New:** *Start a program*
   - Program: `powershell.exe`
   - Arguments: `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\YOURNAME\gmail-agent\run.ps1"`
   - Start in: `C:\Users\YOURNAME\gmail-agent`
5. **Conditions:** untick *Start only if on AC power* and *Stop if switching to battery* (laptops).
6. **Settings:** tick *If the task fails, restart every 1 minute* (3 attempts); untick *Stop the task if it runs longer than*.
7. Click **OK**, right-click the task, and choose **Run**.

Watch the log live:

```powershell
Get-Content $HOME\gmail-agent\agent.log -Wait -Tail 20
```

### 9. Keep Windows awake

A sleeping PC cannot reply. Under **Settings → System → Power & battery**, set *When plugged in, put my device to sleep after* to **Never**. On laptops, set *closing the lid* to **Do nothing** when plugged in. Mail received while the PC sleeps stays unread and is answered when the agent restarts.

## Configuration

All settings are environment variables, normally set in `run.ps1`.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2` | Model name shown by `ollama list` |
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Ollama endpoint |
| `POLL_SECONDS` | `30` | Seconds between inbox checks |
| `DRY_RUN` | `true` | `true` prints replies only; `false` sends them |
| `ALLOWED_SENDERS` | empty | Comma-separated addresses to reply to |
| `ALLOWED_DOMAINS` | empty | Comma-separated domains to reply to, e.g. `yourcompany.com,clientcompany.com` |
| `MAX_REPLIES_PER_SENDER_PER_DAY` | `3` | Rate limit per sender (resets on restart) |
| `SYSTEM_PROMPT` | built-in | Instructions that shape reply content and tone |
| `SIGNATURE` | automated-reply note | Text appended to every reply |
| `GMAIL_CREDENTIALS` | `credentials.json` | Path to the OAuth client file |
| `GMAIL_TOKEN` | `token.json` | Where the login token is stored |

A sender is accepted if their address is in `ALLOWED_SENDERS` **or** their domain is in `ALLOWED_DOMAINS`. If **both are empty, everyone is allowed**, which is not recommended (see [Security](#security-and-limitations)). Domains match exactly: `yourcompany.com` does not cover `mail.yourcompany.com`.

### Writing a good `SYSTEM_PROMPT`

Small models follow concrete facts much better than vague instructions. Include:

- Who the assistant speaks for, and the tone
- Real facts it may use (hours, FAQs, services)
- Hard rules ("never state prices", "never confirm meetings or dates")
- A fallback ("if unsure, say the owner will follow up personally")
- "Output only the reply body"

## Optional: lower Ollama's memory use

Ollama keeps a model loaded for 5 minutes after the last request. To unload sooner:

```powershell
setx OLLAMA_KEEP_ALIVE "2m"
```

Then quit Ollama from the tray and reopen it.

## Security and limitations

- **Keep `credentials.json` and `token.json` private.** Do not commit, upload or share them. To revoke access at any time, remove the app at *myaccount.google.com → Security → Third-party access* and delete `token.json`.
- **Use an allow-list.** With no allow-list, anyone can trigger replies from your address, including spammers and scammers. A stranger can also try prompt injection ("ignore your instructions and..."). Never put secrets in `SYSTEM_PROMPT`. Do not add public domains such as `gmail.com` to `ALLOWED_DOMAINS`.
- **Sender addresses can be forged.** The agent trusts the `From` header. Gmail already filters most forged mail.
- **Local models can be wrong.** Supply facts in the prompt, forbid commitments, keep the disclosure signature, and review sent replies regularly.
- **Gmail limits.** Regular accounts can send roughly 500 emails per day. Mass auto-replies can get an account throttled.
- **Rate limit memory.** The per-sender limit is kept in memory and resets when the agent restarts.
- **Needs a running computer.** The agent only works while the PC is on, awake and logged in.
- Keep Ollama bound to `localhost`. Do not expose port 11434 to the internet.

## Troubleshooting

| Problem | Fix |
|---|---|
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `python is not recognized` | Python is not on PATH. Reinstall with *Add python.exe to PATH* ticked, then open a new PowerShell window. |
| `FileNotFoundError: credentials.json` | File missing, misnamed (`credentials.json.json`) or in the wrong folder. See step 5. |
| **Publish app** is greyed out | Complete and save the **Branding** page first. |
| `Error 403: access_denied` at login | Your Gmail is not under **Audience → Test users**, or you chose a different account. |
| `Error 400: redirect_uri_mismatch` | The client is not a **Desktop app**. Create a new one and download its JSON. |
| `Access blocked: app has not completed verification` | Add yourself under Test users, or publish the app and use **Advanced → Go to app**. |
| `insufficient authentication scopes` | Delete `token.json` and run again. |
| Browser does not open for login | Copy the URL printed in the terminal into your browser. |
| `Connection refused` on port 11434 | Ollama is not running. Open it from the Start menu. |
| `model not found` | `OLLAMA_MODEL` does not match `ollama list`. |
| Task runs but nothing happens | Check `agent.log`. Make sure `DRY_RUN` is `"false"` and the sender is allowed. The mail may already be read, in Promotions/Social, or labeled `AI-Replied`. |
| Same email shown every cycle | Expected in dry-run, which does not label messages. |
| Strange characters in the log | Confirm `$env:PYTHONIOENCODING = "utf-8"` is in `run.ps1`. |
| Login fails after about a week | The app is still in *Testing*. Publish it, delete `token.json`, and log in again. |
| Replies are very slow | Use a smaller model such as `llama3.2:1b`. Email does not need instant replies. |

## Linux / macOS

The same code works. Differences: activate the environment with `source venv/bin/activate`, set variables with `export NAME="value"`, and keep it running with `systemd`, `launchd` or `tmux` instead of Task Scheduler.

## Pre-release checklist

- [ ] Python installed, virtual environment active
- [ ] Ollama running and the model answers a test prompt
- [ ] Gmail API enabled, Desktop app client created, `credentials.json` in place
- [ ] Branding page saved and app published (*In production*)
- [ ] `token.json` created after authorization
- [ ] `ALLOWED_SENDERS` and/or `ALLOWED_DOMAINS` set to specific people or domains
- [ ] Dry-run replies reviewed and approved
- [ ] `DRY_RUN` set to `false` and a live test reply confirmed
- [ ] Scheduled task created and sleep disabled

## License

Add a license of your choice (for example MIT) before publishing.
