# FPL Intelligence Engine — User Onboarding Guide

Welcome to the FPL Intelligence Engine. This guide explains what the platform does, how to get started, and what to expect as a registered or anonymous user.

---

## What is FPL Intelligence Engine?

An AI-powered analysis tool for Fantasy Premier League managers. It analyses your squad, predicts player points using machine learning, recommends transfers and captain picks, and learns from outcomes over time.

You can use it anonymously (no account needed) or register to unlock email alerts and persistent decision history.

---

## 1. Finding Your FPL Team ID

Before you start, you'll need your FPL Team ID. This is a number in the URL when you view your team on the FPL website.

**Steps:**
1. Go to [fantasy.premierleague.com](https://fantasy.premierleague.com)
2. Click **My Team** or **Points**
3. Look at the URL — it will be something like:
   ```
   https://fantasy.premierleague.com/entry/1234567/event/29
   ```
4. Your Team ID is the number between `/entry/` and `/event/` — in this example: **1234567**

Keep this number handy. It's the only thing you need to start using the platform.

---

## 2. Anonymous vs Registered

| Feature | Anonymous | Registered |
|---------|-----------|------------|
| Squad analysis | ✅ Full | ✅ Full |
| Transfer recommendations | ✅ | ✅ |
| Captain picker | ✅ | ✅ |
| Chip timing advice | ✅ | ✅ |
| Pre-deadline email briefing | ❌ | ✅ (opt-in) |
| Weekly strategy report | ❌ | ✅ (opt-in) |
| Decision history | Session only | Persistent |
| AI learns from your decisions | Session only | Across all GWs |
| Data retained | 30 days max | Until you delete account |

**Anonymous** is great for a quick look before committing. Everything analytical works — no account required.

**Registered** users get the full experience: the system remembers your decisions, tracks outcomes, refines its recommendations over time, and sends you alerts before each deadline.

---

## 3. Anonymous Analysis Flow

1. Open the platform at `https://yourdomain.com`
2. On the landing page, enter your **FPL Team ID** in the input field
3. Click **Analyse My Squad**
4. The platform fetches your squad from the FPL API and runs the full analysis pipeline:
   - Predicts expected points (xPts) for every player
   - Recommends the best captain pick
   - Suggests transfer options (if any gain is available)
   - Advises on chip timing based on upcoming fixtures
5. Browse the results — transfers, captain advice, Oracle XI comparison, player intel
6. Your session is active for up to 30 days; nothing is stored permanently

---

## 4. Registered User Flow

### Step 1 — Register

1. On the landing page, click **Register for Weekly Alerts**
2. Enter your:
   - FPL Team ID
   - Email address
3. You'll receive a welcome email confirming your registration
4. You're now registered. The platform will sync your squad automatically before each GW deadline.

> **Note:** There is a cap of 500 registered users. If the cap is reached, you'll be placed on a waitlist and automatically promoted when a spot opens.

### Step 2 — Explore the Dashboard

After registering, all dashboard sections are unlocked:

| Section | What it shows |
|---------|--------------|
| **Squad** | Your current squad with xPts, form, fixture difficulty |
| **Transfers** | AI-recommended transfer options with expected gain |
| **Captain** | Top 3 captain picks ranked by xPts and consistency |
| **Chips** | Chip timing advice (Triple Captain, Bench Boost, Free Hit, Wildcard) |
| **Oracle** | Comparison of your XI vs the AI's optimal £100m XI |
| **Review** | Past GW decisions, actual outcomes, reward scores |
| **Intel** | News, injuries, and sentiment for your players |
| **Lab** | Backtesting, model metrics, and season simulation |

### Step 3 — Log Decisions

When you act on a recommendation (or choose not to), log it in the **Review** section:
- Mark each recommendation as **Followed**, **Ignored**, or **Partially followed**
- If you made a transfer hit (-4 pts), tick **Hit taken**
- The AI uses this feedback to improve its recommendations over the season

---

## 5. Email Alerts

Registered users can opt in to two types of email:

### Pre-deadline briefing (24 hours before deadline)

Sent automatically 24 hours before each GW deadline. Includes:
- Your top transfer recommendation
- Captain pick
- Chip advice if applicable
- Key injury alerts for your players

### Weekly strategy report (post-GW)

Sent after each GW resolves (typically Tuesday). Includes:
- Your GW points vs Oracle XI vs GW top team
- Decision accuracy (how your followed recommendations performed)
- Model performance summary

Both emails come from the address configured by the platform administrator. To stop receiving them, use the unsubscribe link at the bottom of any email.

---

## 6. WhatsApp Alerts (if enabled)

If the platform has WhatsApp configured (via Twilio), you'll receive a 6-hour pre-deadline summary on WhatsApp. This is an optional feature — ask the platform administrator if it's available.

---

## 7. How the AI Learns

The platform improves its recommendations through five feedback loops:

1. **Model calibration**: After each GW, prediction errors are analysed per player position and price band. Corrections are applied to future predictions automatically.

2. **Oracle blind spots**: If the Oracle's optimal XI consistently misses a player over multiple GWs, the model increases its weight on that player's recent form.

3. **News sentiment**: Player injury and form news is scraped daily from 7+ sources. Sentiment scores (-1 to +1) feed directly into the xPts model.

4. **Decision outcomes**: Every recommendation you mark as followed or ignored gets a reward score after the GW resolves. The bandit algorithm uses these to favour strategies that have worked better historically.

5. **Fixture congestion**: Fixtures across all competitions (Premier League, Champions League, Europa League, FA Cup) are synced daily. When a player's team has a European or cup game within three days of a Premier League fixture, the model raises their rotation risk score. This reduces their predicted minutes and xPts to reflect the real chance a manager rests them.

The more GWs you use the platform, the more personalised the recommendations become.

---

## 8. The Oracle

The Oracle is an independent AI that computes the mathematically optimal £100m squad for each GW — without budget or squad constraints from your current team. Think of it as the "perfect information" benchmark.

After each GW, your XI is scored against:
- The **Oracle XI** (what the model would have picked given full freedom)
- The **GW top team** (the actual highest-scoring manager's team)

The gap between your score and the Oracle score is a measure of how much room the AI has to improve your decisions.

---

## 9. Deleting Your Account

To remove your data and unsubscribe:

1. Go to your **Profile** settings (top right)
2. Click **Delete Account**
3. Your squad data, decision history, and email address are permanently removed
4. The next person on the waitlist is automatically promoted and notified

Your data will not be retained after account deletion.

---

## 10. Privacy

- Your FPL Team ID and email address are stored to power your personalised analysis and email alerts
- No payment information is collected
- Squad data is fetched from the official FPL API using your Team ID (the same data visible publicly on the FPL website)
- Anonymous sessions are auto-purged after 30 days
- Data is never sold or shared with third parties

---

## 11. Troubleshooting

| Problem | Fix |
|---------|-----|
| "Team ID not found" | Double-check your FPL Team ID from the URL. Make sure you've played at least one GW. |
| Squad not updating | Use **Sync Squad** from the dashboard. Data is fetched live from FPL. |
| Not receiving emails | Check your spam folder. Ensure your email is correct in your profile. |
| "Waitlist" message on registration | The 500-user cap has been reached. You're on the waitlist and will be notified when a spot opens. |
| xPts seem wrong | Predictions update daily at 08:00. Check the **Intel** tab for injury/availability news that may affect the model. |
| Oracle page blank | The Oracle runs daily at 13:05. If today's GW hasn't been processed yet, yesterday's result is shown. |
