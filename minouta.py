#!/usr/bin/env python3
# ============================================================
# 🕷️ Minouta Web Scraper - Core + CLI + API + Database
# ============================================================

import sys
import re
import csv
import json
import os
from urllib.parse import urljoin
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import box

from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================
# 📝 توابع اصلی استخراج (با رجکس‌های سراسری اما با نام‌های منحصربه‌فرد)
# ============================================================

def normalize_url(user_input: str) -> str:
    if not user_input:
        return ""
    user_input = user_input.strip()
    if '://' not in user_input:
        return 'https://' + user_input
    if user_input.lower().startswith(('http://', 'https://')):
        return user_input
    return user_input

# ✅ رجکس‌ها رو با یه پیشوند خاص تعریف می‌کنیم تا با هیچ متغیر دیگه‌ای تداخل نکنه
_PATTERN_MOBILE = re.compile(r'(?<!\d)(?:0|\+98)9[0-9]{9}(?!\d)')
_PATTERN_LANDLINE = re.compile(r'(?<!\d)(?:\+98|0098)?0[1-8][0-9]{9}(?!\d)')
_PATTERN_EMAIL = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)
_PATTERN_URL = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)
_PATTERN_INSTAGRAM = re.compile(r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?', re.IGNORECASE)
_PATTERN_YOUTUBE = re.compile(r'https?://(?:www\.)?youtube\.com/(?:@|c/|user/|channel/)([a-zA-Z0-9_-]+)/?', re.IGNORECASE)

def _normalize_phone(num: str) -> str:
    if num.startswith('+98'):
        return '0' + num[3:]
    if num.startswith('0098'):
        return '0' + num[4:]
    return num

def extract_phones(text: str):
    mobiles_raw = _PATTERN_MOBILE.findall(text)
    landlines_raw = _PATTERN_LANDLINE.findall(text)
    mobiles = list(dict.fromkeys(_normalize_phone(n) for n in mobiles_raw))
    landlines = list(dict.fromkeys(_normalize_phone(n) for n in landlines_raw))
    return mobiles, landlines

def extract_emails(text: str):
    return list(dict.fromkeys(_PATTERN_EMAIL.findall(text)))

def extract_links(text: str, base_url: str = ""):
    # ✅ استفاده از رجکس سراسری با نام منحصربه‌فرد
    links = _PATTERN_URL.findall(text)
    if base_url:
        absolute_links = []
        for link in links:
            absolute = urljoin(base_url, link)
            if absolute not in absolute_links:
                absolute_links.append(absolute)
        return absolute_links
    return links

def extract_instagram_handles(text: str):
    return list(dict.fromkeys(_PATTERN_INSTAGRAM.findall(text)))

def extract_youtube_handles(text: str):
    return list(dict.fromkeys(_PATTERN_YOUTUBE.findall(text)))

# ============================================================
# 🌐 دریافت محتوا
# ============================================================

def fetch_content(url: str, timeout: int = 10, user_agent: str = None, proxy: str = None) -> str:
    headers = {'User-Agent': user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    proxies = {'http': proxy, 'https': proxy} if proxy else None
    response = requests.get(url, headers=headers, proxies=proxies, timeout=timeout)
    response.raise_for_status()
    return response.text

# ============================================================
# 🧠 کلاس موتور اسکرپر
# ============================================================

@dataclass
class ScrapeResult:
    url: str
    timestamp: datetime
    mobiles: List[str]
    landlines: List[str]
    emails: List[str]
    links: List[str]
    instagram: List[str]
    youtube: List[str]

class ScraperEngine:
    def __init__(self, timeout: int = 10, user_agent: str = None, proxy: str = None):
        self.timeout = timeout
        self.user_agent = user_agent
        self.proxy = proxy

    def scrape(self, url: str,
               extract_mobile: bool = True,
               extract_landline: bool = True,
               extract_email: bool = True,
               extract_links: bool = False,
               extract_instagram: bool = False,
               extract_youtube: bool = False) -> ScrapeResult:
        url = normalize_url(url)
        html = fetch_content(url, timeout=self.timeout,
                             user_agent=self.user_agent,
                             proxy=self.proxy)
        mobiles, landlines = [], []
        if extract_mobile or extract_landline:
            mobiles, landlines = extract_phones(html)
            if not extract_mobile:
                mobiles = []
            if not extract_landline:
                landlines = []

        emails = extract_emails(html) if extract_email else []
        links = extract_links(html, base_url=url) if extract_links else []
        instagram = extract_instagram_handles(html) if extract_instagram else []
        youtube = extract_youtube_handles(html) if extract_youtube else []

        return ScrapeResult(
            url=url,
            timestamp=datetime.now(),
            mobiles=mobiles,
            landlines=landlines,
            emails=emails,
            links=links,
            instagram=instagram,
            youtube=youtube
        )

    def scrape_many(self, urls: List[str], **kwargs) -> List[ScrapeResult]:
        results = []
        for url in urls:
            try:
                results.append(self.scrape(url, **kwargs))
            except Exception as e:
                raise RuntimeError(f"Error scraping {url}: {e}")
        return results

# ============================================================
# 🗄️ پایگاه داده (SQLite با پشتیبانی از متغیر محیطی)
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL_ENV = os.getenv("DATABASE_URL", None)
if DATABASE_URL_ENV:
    SQLALCHEMY_DATABASE_URL = DATABASE_URL_ENV
else:
    import tempfile
    db_dir = tempfile.gettempdir()
    db_path = os.path.join(db_dir, "scraper.db")
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ScrapeHistory(Base):
    __tablename__ = "scrape_history"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.now)
    mobiles = Column(JSON, default=list)
    landlines = Column(JSON, default=list)
    emails = Column(JSON, default=list)
    links = Column(JSON, default=list)
    instagram = Column(JSON, default=list)
    youtube = Column(JSON, default=list)
    raw_data = Column(Text, nullable=True)

Base.metadata.create_all(bind=engine)

class DatabaseManager:
    def __init__(self, session: Session = None):
        self.session = session or SessionLocal()

    def save_result(self, result: ScrapeResult, raw_html: str = None):
        history = ScrapeHistory(
            url=result.url,
            timestamp=result.timestamp,
            mobiles=result.mobiles,
            landlines=result.landlines,
            emails=result.emails,
            links=result.links,
            instagram=result.instagram,
            youtube=result.youtube,
            raw_data=raw_html
        )
        self.session.add(history)
        self.session.commit()
        return history.id

    def get_all(self, limit: int = 100):
        return self.session.query(ScrapeHistory).order_by(ScrapeHistory.timestamp.desc()).limit(limit).all()

    def get_by_id(self, id: int):
        return self.session.query(ScrapeHistory).filter(ScrapeHistory.id == id).first()

    def close(self):
        self.session.close()

# ============================================================
# 🎨 رابط کاربری با Rich (CLI)
# ============================================================

console = Console()

class RichCLI:
    def __init__(self):
        self.engine = ScraperEngine()
        self.db = DatabaseManager()

    def run(self):
        self._show_header()
        while True:
            self._show_menu()
            choice = Prompt.ask(
                "[bold cyan]Select option[/]",
                choices=["1", "2", "3", "4", "5", "q"],
                default="1"
            )
            if choice == "1":
                self._scrape_single()
            elif choice == "2":
                self._scrape_multiple()
            elif choice == "3":
                self._show_history()
            elif choice == "4":
                self._settings()
            elif choice == "5":
                self._export_data()
            elif choice.lower() == "q":
                console.print("[bold red]Goodbye![/]")
                break

    def _show_header(self):
        console.print(Panel.fit(
            "[bold yellow]🕷️ Minouta Web Scraper[/]\n"
            "[italic]Extract phones, emails, links, social IDs[/]",
            border_style="blue"
        ))

    def _show_menu(self):
        console.print("\n[bold]Main Menu[/]")
        console.print("1. Scrape Single URL")
        console.print("2. Scrape Multiple URLs (comma separated)")
        console.print("3. View History")
        console.print("4. Settings (timeout, proxy, user-agent)")
        console.print("5. Export Results")
        console.print("q. Quit")

    def _get_extract_options(self) -> dict:
        console.print("\n[bold]Select data to extract:[/]")
        extract_mobile = Confirm.ask("📱 Mobile", default=True)
        extract_landline = Confirm.ask("🏠 Landline", default=True)
        extract_email = Confirm.ask("✉️ Email", default=True)
        extract_links = Confirm.ask("🔗 Links", default=False)
        extract_instagram = Confirm.ask("📸 Instagram", default=False)
        extract_youtube = Confirm.ask("▶️ YouTube", default=False)
        return {
            "extract_mobile": extract_mobile,
            "extract_landline": extract_landline,
            "extract_email": extract_email,
            "extract_links": extract_links,
            "extract_instagram": extract_instagram,
            "extract_youtube": extract_youtube
        }

    def _scrape_single(self):
        url = Prompt.ask("Enter URL")
        if not url:
            return
        options = self._get_extract_options()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Scraping...", total=None)
            try:
                result = self.engine.scrape(url, **options)
                self.db.save_result(result)
                self._display_result(result)
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")

    def _scrape_multiple(self):
        urls_input = Prompt.ask("Enter URLs (comma separated)")
        urls = [u.strip() for u in urls_input.split(",") if u.strip()]
        if not urls:
            return
        options = self._get_extract_options()
        results = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Scraping multiple pages...", total=len(urls))
            for url in urls:
                try:
                    result = self.engine.scrape(url, **options)
                    self.db.save_result(result)
                    results.append(result)
                except Exception as e:
                    console.print(f"[red]Error on {url}: {e}[/]")
                progress.advance(task)
        for r in results:
            self._display_result(r)

    def _display_result(self, result: ScrapeResult):
        table = Table(title=f"Results for {result.url}", box=box.ROUNDED)
        table.add_column("Type", style="cyan")
        table.add_column("Count", style="magenta")
        table.add_column("Values (first 5)", style="green")

        for key, label in [("mobiles", "📱 Mobile"), ("landlines", "🏠 Landline"),
                           ("emails", "✉️ Email"), ("links", "🔗 Link"),
                           ("instagram", "📸 Instagram"), ("youtube", "▶️ YouTube")]:
            values = getattr(result, key)
            display = values[:5] if values else []
            display_str = "\n".join(display) if display else "—"
            table.add_row(label, str(len(values)), display_str)

        console.print(table)

    def _show_history(self):
        records = self.db.get_all(limit=20)
        if not records:
            console.print("[yellow]No history found.[/]")
            return
        table = Table(title="Scrape History", box=box.SIMPLE)
        table.add_column("ID", style="dim")
        table.add_column("URL", style="cyan")
        table.add_column("Time", style="green")
        table.add_column("Mobiles", justify="right")
        table.add_column("Emails", justify="right")
        for rec in records:
            table.add_row(
                str(rec.id),
                rec.url[:40] + ("..." if len(rec.url) > 40 else ""),
                rec.timestamp.strftime("%Y-%m-%d %H:%M"),
                str(len(rec.mobiles or [])),
                str(len(rec.emails or []))
            )
        console.print(table)

    def _settings(self):
        console.print("[bold]Current Settings:[/]")
        console.print(f"Timeout: {self.engine.timeout}s")
        console.print(f"User-Agent: {self.engine.user_agent or 'Default'}")
        console.print(f"Proxy: {self.engine.proxy or 'None'}")
        if Confirm.ask("Change settings?"):
            self.engine.timeout = IntPrompt.ask("Timeout (seconds)", default=self.engine.timeout)
            ua = Prompt.ask("User-Agent (leave empty for default)", default=self.engine.user_agent or "")
            self.engine.user_agent = ua if ua else None
            proxy = Prompt.ask("Proxy (e.g. http://proxy:8080, leave empty for none)", default=self.engine.proxy or "")
            self.engine.proxy = proxy if proxy else None
            console.print("[green]Settings updated.[/]")

    def _export_data(self):
        records = self.db.get_all(limit=1000)
        if not records:
            console.print("[yellow]No data to export.[/]")
            return
        format = Prompt.ask("Export format", choices=["csv", "json", "txt"], default="csv")
        path = Prompt.ask("File path", default=f"export.{format}")
        data = []
        for rec in records:
            data.append({
                "id": rec.id,
                "url": rec.url,
                "timestamp": rec.timestamp.isoformat(),
                "mobiles": rec.mobiles,
                "landlines": rec.landlines,
                "emails": rec.emails,
                "links": rec.links,
                "instagram": rec.instagram,
                "youtube": rec.youtube
            })
        try:
            if format == "csv":
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)
            elif format == "json":
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:  # txt
                with open(path, 'w', encoding='utf-8') as f:
                    for item in data:
                        f.write(f"ID: {item['id']}\nURL: {item['url']}\nTime: {item['timestamp']}\n")
                        for key in ['mobiles', 'landlines', 'emails', 'links', 'instagram', 'youtube']:
                            if item[key]:
                                f.write(f"{key}: {', '.join(item[key])}\n")
                        f.write("\n")
            console.print(f"[green]Exported to {path}[/]")
        except Exception as e:
            console.print(f"[red]Export error: {e}[/]")

# ============================================================
# 🌐 سرور وب (FastAPI) با CORS و دیتابیس
# ============================================================

app = FastAPI(title="Minouta Scraper API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_manager = DatabaseManager()

class ScrapeRequest(BaseModel):
    urls: List[str]
    timeout: Optional[int] = 10
    user_agent: Optional[str] = None
    proxy: Optional[str] = None
    extract_mobile: bool = True
    extract_landline: bool = True
    extract_email: bool = True
    extract_links: bool = False
    extract_instagram: bool = False
    extract_youtube: bool = False
    save_history: bool = True

@app.post("/scrape")
def scrape_api(request: ScrapeRequest):
    engine = ScraperEngine(
        timeout=request.timeout,
        user_agent=request.user_agent,
        proxy=request.proxy
    )
    results = []
    for url in request.urls:
        try:
            result = engine.scrape(
                url,
                extract_mobile=request.extract_mobile,
                extract_landline=request.extract_landline,
                extract_email=request.extract_email,
                extract_links=request.extract_links,
                extract_instagram=request.extract_instagram,
                extract_youtube=request.extract_youtube
            )
            if request.save_history:
                db_manager.save_result(result)

            result_dict = asdict(result)
            result_dict['timestamp'] = result_dict['timestamp'].isoformat()
            results.append(result_dict)

        except Exception as e:
            results.append({"url": url, "error": str(e)})
    return JSONResponse(content={"results": results})

@app.get("/history")
def history_api(limit: int = 20):
    records = db_manager.get_all(limit=limit)
    return [
        {
            "id": r.id,
            "url": r.url,
            "timestamp": r.timestamp.isoformat(),
            "mobiles": r.mobiles,
            "landlines": r.landlines,
            "emails": r.emails,
            "links": r.links,
            "instagram": r.instagram,
            "youtube": r.youtube
        }
        for r in records
    ]

@app.get("/history/{id}")
def get_history_item(id: int):
    rec = db_manager.get_by_id(id)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": rec.id,
        "url": rec.url,
        "timestamp": rec.timestamp.isoformat(),
        "mobiles": rec.mobiles,
        "landlines": rec.landlines,
        "emails": rec.emails,
        "links": rec.links,
        "instagram": rec.instagram,
        "youtube": rec.youtube
    }

@app.get("/ping")
def ping():
    return {"status": "ok"}

# ============================================================
# 🚀 نقطه ورود برنامه
# ============================================================

def main():
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode == "api":
            uvicorn.run(app, host="0.0.0.0", port=8000)
            return
        elif mode == "cli":
            cli = RichCLI()
            cli.run()
            return
        elif mode == "simple":
            if len(sys.argv) < 3:
                print("Usage: python minouta.py simple <url> [url2 ...]")
                return
            urls = sys.argv[2:]
            engine = ScraperEngine()
            for url in urls:
                try:
                    result = engine.scrape(
                        url,
                        extract_mobile=True,
                        extract_landline=True,
                        extract_email=True,
                        extract_links=True,
                        extract_instagram=True,
                        extract_youtube=True
                    )
                    print(f"Results for {url}:")
                    print(f"  Mobiles: {result.mobiles}")
                    print(f"  Landlines: {result.landlines}")
                    print(f"  Emails: {result.emails}")
                    print(f"  Links: {result.links}")
                    print(f"  Instagram: {result.instagram}")
                    print(f"  YouTube: {result.youtube}")
                except Exception as e:
                    print(f"Error on {url}: {e}")
            return
        else:
            print("Unknown mode. Available: cli, api, simple")
            return

    cli = RichCLI()
    cli.run()

if __name__ == "__main__":
    main()