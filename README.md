# Instagram Non-Mutual Followers Checker

**Web tool that finds accounts you follow but who do NOT follow you back**  
(also known as "non-mutuals", "ghost followers", or "people not following you back").

**Current status (as of March 2026)**: Still using Instagram private API endpoints (they still work as of early 2026, but always fragile).

## How It Works – Step by Step

1. You enter your **Instagram username** + **sessionid** cookie value  
2. The tool verifies that the sessionid actually belongs to the username you provided  
   (prevents people from abusing someone else's login)  
3. Checks how many times **you** have already used the tool in the last 24 hours  
   → Normal limit = **3 runs per 24 hours** per username  
   → Uses MongoDB to remember usage  
4. Fetches your numeric Instagram user ID  
5. Downloads your **followers** list (paginated API calls)  
6. Downloads your **following** list (paginated API calls)  
7. Compares the two lists → finds usernames present in **following** but missing from **followers**  
8. (Optional) Filters out verified accounts if you checked the box  
9. Streams the list of non-mutual usernames **live** to your browser using Server-Sent Events (SSE)  
   → You see names appearing gradually instead of waiting 30–120 seconds  
10. Saves the fact that you ran the tool (updates timestamp + counter in MongoDB)

## Main Technologies

- **Backend**          Flask (Python)  
- **Real-time output** Server-Sent Events (SSE)  
- **Instagram API**    Private mobile endpoints (`i.instagram.com/api/v1/…`)  
- **Proxy**            Residential / sticky-session proxy (Decodo / similar recommended)  
- **Storage**          MongoDB – only used for per-user run limiting (3× per day)  
- **Security**         Very basic – verifies session belongs to claimed username

## Important Warnings (2026 edition)

- This uses **unofficial/private** Instagram API → **can stop working any day**
- Instagram **bans accounts** that make too many requests or show suspicious patterns
- Using this tool **multiple times per day / every day** → very high ban risk
- Free/public proxies → almost instant block
- Residential proxies + low frequency → still risky but much safer
- **Never** use your main/personal account for heavy testing
- Tool does **not** unfollow anyone – it only shows names

## Setup – Quick Version

```bash
# 1. Create .env file with these values
MONGO_URI=          mongodb+srv://...
MONGO_DB_NAME=      ig_tools
MONGO_COLLECTION_NAME=usage

DECODO_USERNAME=    your-proxy-username
DECODO_PASSWORD=    your-proxy-password

# 2. Install
pip install flask requests pymongo urllib3

# 3. Run
python app.py
# → opens http://localhost:5000


Readme generated with Grok (X) AI
