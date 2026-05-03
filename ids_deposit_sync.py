#!/usr/bin/env python3
"""
IDS Previous Deposits Sync Script
===================================
1. Reads Previous-Deposits.xlsx
2. Uploads all deposit rows into MongoDB collection: previous_deposits
3. Cross-references with reservations collection:
   - If reservation_no found in deposits → set Rate = net amount, main_remark = "Already paid £<amount>"
   - If NOT found → main_remark = "Please check the payment with the guest <main_client> (channel)"
4. One-time sync — safe to re-run (uses upsert)
"""

import pymongo
import pandas as pd
from datetime import datetime

# ─── MongoDB Connection ───────────────────────────────────────────────────────
mclient = pymongo.MongoClient(
    "mongodb+srv://jayeetrab:mGhnfdMwFeFZwx6L@cohortconnect.lcpylgn.mongodb.net/"
)
db = mclient["Reservations"]  # Change if your DB name is different

reservations_col = db["reservations"]
deposits_col     = db["previous_deposits"]

# ─── Step 1: Load & Clean Excel ───────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Loading Previous-Deposits.xlsx")
print("=" * 60)

df = pd.read_excel("Previous-Deposits.xlsx")
df.columns = [c.strip() for c in df.columns]

# Clean reservation_no → always store as string (matches MongoDB format like "150232685.0")
df["reservation_no"] = df["reservation_no"].astype(str).str.strip()

# Clean amount → numeric
df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

# Drop rows with no amount
df = df.dropna(subset=["amount"])

print(f"  Total rows loaded        : {len(df)}")
print(f"  Unique reservation nos   : {df['reservation_no'].nunique()}")
print(f"  Rows with null amount    : {df['amount'].isna().sum()} (dropped)")

# ─── Step 2: Aggregate — sum all amounts per reservation_no ──────────────────
# A reservation may have multiple deposit rows (partial payments, refunds etc.)
# We sum them to get the NET deposit amount.
agg = (
    df.groupby("reservation_no", as_index=False)["amount"]
    .sum()
    .rename(columns={"amount": "total_amount"})
)

print(f"  Aggregated unique res nos: {len(agg)}")
print(f"  Positive net deposits    : {(agg['total_amount'] > 0).sum()}")
print(f"  Zero/negative net        : {(agg['total_amount'] <= 0).sum()}")

# ─── Step 3: Upload to MongoDB previous_deposits collection ──────────────────
print()
print("=" * 60)
print("STEP 2: Uploading to MongoDB → previous_deposits")
print("=" * 60)

# Build documents — one per unique reservation_no (net total)
deposits_docs = []
for _, row in agg.iterrows():
    deposits_docs.append({
        "reservation_no" : row["reservation_no"],
        "total_amount"   : round(float(row["total_amount"]), 2),
        "currency"       : "GBP",
        "synced_at"      : datetime.utcnow().isoformat(),
    })

# Upsert each document so re-running is always safe
inserted = 0
updated  = 0
for doc in deposits_docs:
    result = deposits_col.update_one(
        {"reservation_no": doc["reservation_no"]},   # filter
        {"$set": doc},                                # update
        upsert=True                                   # insert if not found
    )
    if result.upserted_id:
        inserted += 1
    else:
        updated += 1

print(f"  ✅ Inserted (new)  : {inserted}")
print(f"  🔄 Updated (exist) : {updated}")
print(f"  📦 Total in collection: {deposits_col.count_documents({})}")

# ─── Step 4: Cross-reference with reservations ───────────────────────────────
print()
print("=" * 60)
print("STEP 3: Cross-referencing with reservations collection")
print("=" * 60)

# Build a quick lookup dict: reservation_no → total_amount
deposit_lookup = {doc["reservation_no"]: doc["total_amount"] for doc in deposits_docs}

# Fetch all reservations from MongoDB
all_reservations = list(reservations_col.find({}, {
    "_id": 1,
    "reservation_no": 1,
    "main_client": 1,
    "channel": 1,
}))

print(f"  Total reservations in DB : {len(all_reservations)}")

matched   = 0
unmatched = 0
skipped   = 0

for res in all_reservations:
    res_no = str(res.get("reservation_no", "")).strip()

    # Normalise: strip trailing .0 if present for matching
    # MongoDB might store as "150232685.0" or "150232685" — try both
    res_no_clean = res_no.rstrip("0").rstrip(".") if "." in res_no else res_no

    # Try both forms in the lookup
    amount = deposit_lookup.get(res_no) or deposit_lookup.get(res_no_clean)

    if not res_no:
        skipped += 1
        continue

    if amount is not None and amount > 0:
        # ── FOUND: reservation has a deposit ──────────────────────────────
        matched += 1
        amount_str = f"£{amount:,.2f}".rstrip("0").rstrip(".")
        reservations_col.update_one(
            {"_id": res["_id"]},
            {
                "$set": {
                    "rate"        : amount,          # New Rate field
                    "main_remark" : f"Already paid {amount_str}",
                    "updated_at"  : datetime.utcnow().isoformat(),
                }
            }
        )
    else:
        # ── NOT FOUND: ask staff to check payment ─────────────────────────
        unmatched += 1
        main_client = str(res.get("main_client") or "").strip() or "the client"
        channel     = str(res.get("channel") or "").strip()

        if channel and channel.lower() not in main_client.lower():
            client_label = f"{main_client} ({channel})"
        else:
            client_label = main_client

        reservations_col.update_one(
            {"_id": res["_id"]},
            {
                "$set": {
                    "rate"        : 100,             # Default £100 as before
                    "main_remark" : f"Please check the payment with the guest {client_label}",
                    "updated_at"  : datetime.utcnow().isoformat(),
                }
            }
        )

print()
print("=" * 60)
print("SYNC COMPLETE")
print("=" * 60)
print(f"  ✅ Matched   (deposit found, rate updated)   : {matched}")
print(f"  ⚠️  Unmatched (no deposit, check required)   : {unmatched}")
print(f"  ⏭️  Skipped   (no reservation_no in record)  : {skipped}")
print(f"  📅 Sync time : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
print("=" * 60)

mclient.close()
print("\nMongoDB connection closed. Done.")
