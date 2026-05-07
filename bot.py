import os
import json
import traceback
import asyncio

from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from telegram import InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler
)

# ================== CONFIG ==================

TOKEN = os.getenv("TOKEN")

GROUP_ID = int(
    os.getenv("GROUP_ID")
)

ADMIN_IDS = list(
    map(
        int,
        os.getenv("ADMIN_IDS", "").split(",")
    )
)

DATA_FILE = "data.json"

# ================== DATA ==================

def load_data():

    try:

        with open(DATA_FILE, "r") as f:

            return json.load(f)

    except:

        return {
            "users": {},
            "polls": {}
        }


def save_data(data):

    with open(DATA_FILE, "w") as f:

        json.dump(data, f, indent=4)

        f.flush()


# ================== LOAD SCHEDULE ==================

def load_schedule():

    print("📂 Loading schedule.json")

    with open("test_schedule.json", "r") as f:

        raw = json.load(f)

    schedule = []

    for match in raw:

        create_time = datetime.strptime(
            match["create_time"],
            "%Y-%m-%d %H:%M"
        ).replace(
            tzinfo=ZoneInfo("Asia/Kolkata")
        )

        close_time = datetime.strptime(
            match["close_time"],
            "%Y-%m-%d %H:%M"
        ).replace(
            tzinfo=ZoneInfo("Asia/Kolkata")
        )

        schedule.append({

            "match_no": str(match["match_no"]),

            "team1": match["team1"],

            "team2": match["team2"],

            "type": match["type"],

            "create_time": create_time,

            "close_time": close_time

        })

    print("✅ SCHEDULE LOADED")

    return schedule


MATCH_SCHEDULE = load_schedule()

# ================== CREATE POLL ==================

async def create_poll_auto(context, match):

    try:

        data = load_data()

        match_no = match["match_no"]

        if match_no in data["polls"]:
            return

        current_time = datetime.now(
            ZoneInfo("Asia/Kolkata")
        )

        if current_time < match["create_time"]:
            return

        if match["type"] == "normal":

            high = 100
            low = 50

        elif match["type"] == "double":

            high = 300
            low = 150

        else:

            high = 1000
            low = 500

        options = [

            f"{match['team1']} {high}",
            f"{match['team2']} {high}",
            f"{match['team1']} {low}",
            f"{match['team2']} {low}"

        ]

        print(f"🟢 Creating Match {match_no}")

        message = await context.bot.send_poll(

            chat_id=GROUP_ID,

            question=(
                f"{match_no}. "
                f"{match['team1']} vs {match['team2']}"
            ),

            options=options,

            is_anonymous=False

        )

        data["polls"][match_no] = {

            "poll_id": message.poll.id,
            "message_id": message.message_id,
            "options": options,
            "votes": {},
            "closed": False,
            "updated": False,
            "type": match["type"]

        }

        save_data(data)

        await context.bot.pin_chat_message(
            GROUP_ID,
            message.message_id
        )

        print(f"✅ MATCH {match_no} CREATED")

    except:

        print("❌ CREATE POLL ERROR")
        traceback.print_exc()


# ================== CLOSE POLL ==================

async def close_poll_auto(context, match):

    try:

        data = load_data()

        match_no = match["match_no"]

        if match_no not in data["polls"]:
            return

        poll = data["polls"][match_no]

        if poll["closed"]:
            return

        current_time = datetime.now(
            ZoneInfo("Asia/Kolkata")
        )

        if current_time < match["close_time"]:
            return

        await context.bot.stop_poll(
            GROUP_ID,
            poll["message_id"]
        )

        poll["closed"] = True

        save_data(data)

        print(f"⛔ MATCH {match_no} CLOSED")

    except:

        print("❌ CLOSE POLL ERROR")
        traceback.print_exc()


# ================== SCHEDULER ==================

async def scheduler(context):

    try:

        print("🔁 Scheduler running")

        for match in MATCH_SCHEDULE:

            await create_poll_auto(context, match)

            await close_poll_auto(context, match)

    except:

        print("❌ SCHEDULER ERROR")
        traceback.print_exc()


# ================== HANDLE VOTES ==================

async def handle_vote(update, context):

    try:

        answer = update.poll_answer

        poll_id = answer.poll_id

        user = answer.user

        data = load_data()

        for match_no, poll in data["polls"].items():

            if poll["poll_id"] == poll_id:

                if str(user.id) not in data["users"]:

                    data["users"][str(user.id)] = {

                        "name": user.first_name,
                        "points": 0

                    }

                if answer.option_ids:

                    poll["votes"][str(user.id)] = (
                        answer.option_ids[0]
                    )

                else:

                    poll["votes"].pop(
                        str(user.id),
                        None
                    )

                save_data(data)

                print(f"🗳 Vote from {user.first_name}")

                return

    except:

        print("❌ VOTE ERROR")
        traceback.print_exc()


# ================== UPDATE RESULT ==================

async def update_result(update, context):

    try:

        if update.effective_user.id not in ADMIN_IDS:
            return

        try:

            match_no = str(context.args[0])

            winner = context.args[1].upper()

        except:

            await update.message.reply_text(
                "Usage: /update 49 SRH"
            )

            return

        data = load_data()

        if match_no not in data["polls"]:

            await update.message.reply_text(
                "Invalid match"
            )

            return

        poll = data["polls"][match_no]

        if poll["updated"]:

            await update.message.reply_text(
                "Already updated"
            )

            return

        options = poll["options"]

        votes = poll["votes"]

        for uid in data["users"]:

            user = data["users"][uid]

            vote = votes.get(uid)

            if vote is None:

                user["points"] -= 25

                continue

            option_text = options[vote]

            team, pts = option_text.split()

            pts = int(pts)

            if team == winner:

                user["points"] += pts

            else:

                user["points"] -= pts // 2

        poll["updated"] = True

        save_data(data)

        try:

            await context.bot.unpin_chat_message(
                GROUP_ID,
                poll["message_id"]
            )

        except:
            pass

        await send_leaderboard(context)

        await update.message.reply_text(
            f"✅ Match {match_no} updated"
        )

    except:

        print("❌ UPDATE ERROR")
        traceback.print_exc()


# ================== LEADERBOARD ==================

async def send_leaderboard(context):

    try:

        data = load_data()

        users = sorted(

            data["users"].items(),

            key=lambda x: x[1]["points"],

            reverse=True

        )

        updated_matches = [

            int(m)
            for m, p in data["polls"].items()
            if p["updated"]

        ]

        latest_match = "0"

        if updated_matches:

            latest_match = str(
                max(updated_matches)
            )

        text = (
            "🏆 <b>IPL Prediction Leaderboard</b>\n\n"
        )

        for i, (uid, user) in enumerate(users, 1):

            tag = (
                f'<a href="tg://user?id={uid}">'
                f'{user["name"]}</a>'
            )

            if i == 1:
                prefix = "🥇"

            elif i == 2:
                prefix = "🥈"

            elif i == 3:
                prefix = "🥉"

            else:
                prefix = f"{i}."

            text += (
                f"{prefix} {tag} — "
                f"<b>{user['points']}</b> pts\n"
            )

        text += (
            f"\n📌 Updated after Match "
            f"{latest_match}"
        )

        await context.bot.send_message(

            GROUP_ID,

            text,

            parse_mode="HTML"

        )

    except:

        print("❌ LEADERBOARD ERROR")
        traceback.print_exc()


async def leaderboard(update, context):

    await send_leaderboard(context)


# ================== PING ==================

async def ping(update, context):

    await update.message.reply_text(
        "🏓 Bot alive"
    )


# ================== KEEP ALIVE ==================

async def keep_alive(context):

    print("✅ BOT STILL RUNNING")


# ================== BACKUP ==================

async def backup(update, context):

    try:

        if update.effective_user.id not in ADMIN_IDS:
            return

        with open(DATA_FILE, "rb") as f:

            await context.bot.send_document(

                chat_id=update.effective_chat.id,

                document=InputFile(f),

                filename="data_backup.json"

            )

    except:

        print("❌ BACKUP ERROR")
        traceback.print_exc()


# ================== ERROR HANDLER ==================

async def error_handler(update, context):

    print("\n❌ TELEGRAM ERROR ❌\n")

    traceback.print_exception(
        type(context.error),
        context.error,
        context.error.__traceback__
    )

    print("\n❌ END ERROR ❌\n")


# ================== WEB SERVER ==================

def run_web():

    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot running")

        def do_HEAD(self):

            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):

            return

    port = int(
        os.environ.get("PORT", 10000)
    )

    print(f"🌐 WEB RUNNING ON {port}")

    HTTPServer(
        ("0.0.0.0", port),
        Handler
    ).serve_forever()


# ================== MAIN ==================

def main():

    print("🔥 BOT STARTING")

    asyncio.get_event_loop().set_debug(False)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        CommandHandler("update", update_result)
    )

    app.add_handler(
        CommandHandler("leaderboard", leaderboard)
    )

    app.add_handler(
        CommandHandler("ping", ping)
    )

    app.add_handler(
        CommandHandler("backup", backup)
    )

    app.add_handler(
        PollAnswerHandler(handle_vote)
    )

    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(
        scheduler,
        interval=10,
        first=5
    )

    app.job_queue.run_repeating(
        keep_alive,
        interval=300,
        first=10
    )

    Thread(
        target=run_web,
        daemon=True
    ).start()

    print("🚀 BOT STARTED")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=None,
        close_loop=False,
        stop_signals=None,
        bootstrap_retries=-1,
        poll_interval=2,
        timeout=30,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30
    )


if __name__ == "__main__":

    main()
