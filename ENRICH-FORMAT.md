# enrich/<slug>.json — richer product data per category

Each category gets ONE file `enrich/<category-slug>.json` (e.g. `enrich/towel-warmer.json`). `build.py` merges it into the
board items by id, so research sessions never need to touch `build.py` for this. (Items themselves — name/price/link/img/imgs/desc —
still come from `build.py` as before.)

```json
{
  "cat": "מחמם מגבות",
  "criteria": [
    {"k":"watt","label":"הספק","unit":"W","type":"num","weight":5,"higherBetter":true,
     "goal":{"min":1000},"goalNote":"חדר רחצה הורים ≈9.4 מ״ר — צריך ~1,000W+ כדי שיחמם את החדר",
     "filter":true,"sort":true},
    {"k":"finish","label":"גימור","type":"text","weight":3,"scoreMap":{"רוז גולד":1,"זהב מוברש":0.8,"אחר":0.2}},
    {"k":"warranty","label":"אחריות","unit":"שנים","type":"num","weight":2,"higherBetter":true,"goal":{"min":3}},
    {"k":"ip","label":"עמידות למים","type":"text","weight":1}
  ],
  "items": {
    "TW2": {
      "specs": {"watt":76,"finish":"רוז גולד","warranty":3,"ip":"IPX1"},
      "stores": [
        {"n":"ebath","p":1190,"l":"https://…","rec":true,"note":"יבואן, אחריות 3 שנים"},
        {"n":"Zap – החשמל לצרכן","p":1150,"l":"https://…"},
        {"n":"Amazon IL","p":1290,"l":"https://…"}
      ],
      "pick": true,
      "pickWhy": "הכי טוב ביחס מחיר/איכות/אחריות מבין הרוז גולד שנמצאו",
      "points": ["הכי חשוב: …","…","הכי פחות חשוב: …"]
    }
  }
}
```

## Rules
* **criteria**: ordered **most important → least important** (this order is what the card and the comparison show). 4–8 criteria that matter for *this* category and for Yael's situation
  (e.g. towel warmer / bathroom heater: wattage enough for the parents' bathroom; sofas: sleeping size, fabric washability with a cat+dog; wardrobes: interior width/height, door type…).
  * `type`: `"num"` (with `unit`, `higherBetter`, optional `goal` {min,max,ideal}) or `"text"` (optional `scoreMap` value→0..1).
  * `weight` 1–5 = importance for the score (0–100 "התאמה"). `filter:true` / `sort:true` expose the criterion as a filter and a sort option on the board.
  * `goalNote` = one sentence on *why* the goal (shown next to the criterion).
* **specs**: values for every criterion you can verify from the product page / manufacturer. Missing = leave the key out (the card shows "לא צוין").
  **Prefer products whose spec is published** — if a spec the category needs isn't published, say so in `points`, and try to find a better-documented product.
* **stores**: **2–3 different stores selling the same model**, each with real price + direct product link; `rec:true` on ONE (the store you recommend: stock, reviews, warranty, importer).
  Verify each price on the page (Zap model pages list stores + reviews). If only one store exists, give one and say so in `note`.
* **pick**: `true` on at most ONE item per category — your recommendation after research (the board shows "⭐ ההמלצה שלנו" + `pickWhy`).
* **points**: 4–6 short bullets, **ordered from most to least important for the decision** (replaces the long free-text on the card; the long `desc` stays under "פרטים מלאים").
* All items of a category must be comparable on the same criteria — same keys for every item.
* Don't invent values. Unverified → leave out and mention in `points` ("לא אומת: …").
