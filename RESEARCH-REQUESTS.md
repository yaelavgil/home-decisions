# Research requests (board → Claude → board)

The board lets Yael change a category's *search parameters* (⚙ הגדרות הקטגוריה → "פרמטרים לחיפוש"). When she saves a change (or presses 🔎 חיפוש מחדש) the page writes a **request** to Firebase RTDB; a Claude session researches and writes **suggestions** back; the page shows them at the top of the category so she can *add* or *replace* an existing item.

Firebase base: `https://home-picks-47450-default-rtdb.europe-west1.firebasedatabase.app` (REST, no auth). These paths are separate from `/picks` on purpose (the board polls `/picks` every 5 s).

## 1. Request — `GET /requests.json?orderBy="status"&equalTo="pending"`
`/requests/<reqId>`:
```json
{"cat":"מקרר","label":"מקרר","status":"pending","reason":"params-changed|manual","by":"יעל","at":1791600000000,
 "search":{"quality":"5","life":"years","reviews":true,"budgetMin":"3000","budgetMax":"8000","count":"4","style":"…","stores":"…","avoid":"…","must":"…","notes":"…"},
 "criteria":[ …criteria of the category from enrich/<slug>.json (may be empty)… ],
 "items":[{"id":"R1","name":"…","price":5000,"status":"chosen|discuss|rejected|ordered"}], "site":"https://…/home-decisions/"}
```
* `quality` 1/3/5 = how important quality & durability are (5 = materials, long-term reviews, known-store reliability matter most); `life` temp|normal|years; `reviews:true` = only products/stores with good reviews.
* `count` = how many suggestions to bring (default 4). Budget is per item (₪).

## 2. What the Claude session does
1. `PATCH /requests/<reqId>.json {"status":"running"}`.
2. Follow the standing workflow (memory: `home-product-search-workflow.md`): **check the room/space plans first** (plans, מקור-אמת.md, renovation chats) and ask Yael if data is missing; use her store lists/taste notes; verify prices/specs on product pages; **2–3 stores per item**; specs for the category criteria; ordered `points`.
3. Do not duplicate existing items (`items`); items with status `ordered`/`chosen` are never replaced. For each suggestion say *why* it fits the new parameters and, if it clearly supersedes an existing item, set `replaces` to that item's id.
4. Write `PUT /suggestions/<reqId>.json`:
```json
{"cat":"מקרר","createdAt":1791600500000,"summary":"נמצאו 3 הצעות …",
 "items":{"0":{"name":"…","price":5200,"link":"https://… (recommended store)","img":"https://… (direct image URL)","imgs":["…","…"],
   "desc":"✔ יש… ✘ אין… 📐… 💰…","tags":["…"],"loc":"","why":"…","replaces":"R2",
   "stores":[{"n":"…","p":5200,"l":"https://…","rec":true}],
   "specs":{"watt":1000},"points":["most important…","…"],"status":"new"}}}
```
   (`specs` keys must match `criteria[].k`.) Image URLs should be hot-linkable; the board can't host files from this path.
5. `PATCH /requests/<reqId>.json {"status":"done","summary":"…"}` (if nothing better was found: status `done` + summary "לא נמצא משהו מתאים יותר"). On failure: `{"status":"error","summary":"…"}`.
6. Never buy anything or message anyone. Report back to the main session in 2–3 lines.

The board shows 🔎 "חיפוש מחדש נשלח/מתבצע" while status is pending/running, and 💡 "N הצעות חדשות" once suggestions with `status:"new"` exist.
