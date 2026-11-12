"""Re-render the demo example screenshots from integrations/photo-frame/index.html.
Demo data only (example service names, demo seeds). Run from the repo root:
  pip install playwright && playwright install chromium (or set CHROME_PATH) && python3 integrations/photo-frame/tools/render_demo_screens.py
Posters are fetched from image.tmdb.org and embedded as data URIs (the page CSP allows data: images only).
"""
import json, asyncio, base64, os, urllib.request
from playwright.async_api import async_playwright
P="https://image.tmdb.org/t/p/w342/"
def card(slot,title,tid,year,poster,rating,why,desc,credits,sub=None,free=None,rent=None,buy=None):
    return dict(slot_id=slot,title=title,tmdb_id=tid,year=year,poster="data:image/jpeg;base64,"+base64.b64encode(urllib.request.urlopen(P+poster).read()).decode(),rating=rating,why=why,description=desc,credits=credits,
        watch_availability=dict(status="verified_offers",home_offers=True,theaters_only=False,subscription=sub or [],free=free or [],rent=rent or [],buy=buy or []))
DOC=dict(revision=1,reported_subscriptions=[],genres=[dict(genre_id="comedy",label="Comedy",new=None,classic=None),
 dict(genre_id="scifi",label="Sci-Fi",
   new=card("scifi-new","Dune: Part Two",693134,2024,"6izwz7rsy95ARzTR3poZ8H6c5pp.jpg",82,
     "Demo: shares Science Fiction with a demo seed title (thumbs up).",
     "Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family.",
     "Denis Villeneuve; Timothée Chalamet, Zendaya",sub=["Example Streamer A"],rent=["Example Store"],buy=["Example Store"]),
   classic=card("scifi-classic","Total Recall",861,1990,"wVbeL6fkbTKSmNfalj4VoAUUqJv.jpg",73,
     "Demo: shares a director with a demo seed title (thumbs up).",
     "Construction worker Douglas Quaid's obsession with the planet Mars leads him to visit Recall, a company that manufactures memories.",
     "Paul Verhoeven; Arnold Schwarzenegger, Rachel Ticotin",sub=["Example Streamer B"],free=["Example Free Channel"])),
 dict(genre_id="action",label="Action & Adventure",
   new=card("action-new","Top Gun: Maverick",361743,2022,"n0YuM4f5lvGAP6MAW2kBIzugXnc.jpg",82,
     "Demo: shares Action with a demo seed title (thumbs up).",
     "After more than thirty years of service as one of the Navy's top aviators, Pete \"Maverick\" Mitchell trains a new generation of pilots.",
     "Joseph Kosinski; Tom Cruise, Miles Teller",sub=["Example Streamer A"]),
   classic=card("action-classic","The Terminator",218,1984,"qvktm0BHcnmDpul4Hz01GIazWPr.jpg",77,
     "Demo: shares a lead actor with a demo seed title (thumbs up).",
     "In the post-apocalyptic future, a cyborg assassin is sent back to 1984 to kill Sarah Connor.",
     "James Cameron; Arnold Schwarzenegger, Linda Hamilton",free=["Example Free Channel"],rent=["Example Store"])),
] + [dict(genre_id=g,label=l,new=None,classic=None) for g,l in (("drama","Drama"),("thriller","Thriller"),("family","Family"))],in_theaters=dict(status="checked",items=[],note="Example cinema listings"))
async def main():
    html=open('integrations/photo-frame/index.html').read()
    inj='<script>window.__DOC='+json.dumps(DOC)+';</script>'
    html=html.replace('<script>',inj+'<script>',1) if '<script>' in html else html
    open('/tmp/moviebot-demo.html','w').write(html)
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None, args=["--no-sandbox"])
        pg=await b.new_page(viewport=dict(width=1280,height=800))
        for g,out in (("scifi","scifi.png"),("action","action-adventure.png")):
            await pg.goto('file:///tmp/moviebot-demo.html'); await pg.wait_for_timeout(800)
            await pg.evaluate("g => window.__genre(g)", g); await pg.wait_for_timeout(800)
            await pg.screenshot(path='integrations/photo-frame/docs/images/'+out)
        await b.close()
asyncio.run(main())
