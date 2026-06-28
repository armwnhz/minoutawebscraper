#!/usr/bin/env python3
# ============================================================
# 🕷️ Minouta Web Scraper - Core + CLI + API + Full Web UI
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
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# ============================================================
# 📝 توابع اصلی استخراج
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

_MOBILE_REGEX = re.compile(r'(?<!\d)(?:0|\+98)9[0-9]{9}(?!\d)')
_LANDLINE_REGEX = re.compile(r'(?<!\d)(?:\+98|0098)?0[1-8][0-9]{9}(?!\d)')
_EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.IGNORECASE)
_INSTAGRAM_REGEX = re.compile(r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?', re.IGNORECASE)
_YOUTUBE_REGEX = re.compile(r'https?://(?:www\.)?youtube\.com/(?:@|c/|user/|channel/)([a-zA-Z0-9_-]+)/?', re.IGNORECASE)

def extract_links(text: str, base_url: str = ""):
    return []  # غیرفعال شده به دلیل خطای bool

def _normalize_phone(num: str) -> str:
    if num.startswith('+98'):
        return '0' + num[3:]
    if num.startswith('0098'):
        return '0' + num[4:]
    return num

def extract_phones(text: str):
    mobiles_raw = _MOBILE_REGEX.findall(text)
    landlines_raw = _LANDLINE_REGEX.findall(text)
    mobiles = list(dict.fromkeys(_normalize_phone(n) for n in mobiles_raw))
    landlines = list(dict.fromkeys(_normalize_phone(n) for n in landlines_raw))
    return mobiles, landlines

def extract_emails(text: str):
    return list(dict.fromkeys(_EMAIL_REGEX.findall(text)))

def extract_instagram_handles(text: str):
    return list(dict.fromkeys(_INSTAGRAM_REGEX.findall(text)))

def extract_youtube_handles(text: str):
    return list(dict.fromkeys(_YOUTUBE_REGEX.findall(text)))

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
# 🎨 رابط کاربری با Rich (CLI) - همان کد قبلی
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
# 🌐 صفحه وب - رابط کاربری گرافیکی پیشرفته
# ============================================================

HTML_PAGE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🕷️ Minouta Web Scraper</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
            min-height: 100vh;
            padding: 20px;
            color: #e8e8e8;
        }
        .container {
            max-width: 1100px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 2.8rem;
            background: linear-gradient(135deg, #4facfe, #00f2fe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .header p {
            color: #a0b4c8;
            margin-top: 8px;
            font-size: 1.1rem;
        }
        .tabs {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin-bottom: 25px;
        }
        .tab-btn {
            padding: 12px 30px;
            background: rgba(255,255,255,0.05);
            border: 2px solid #2a3f5f;
            border-radius: 12px;
            color: #b0c4de;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            font-family: inherit;
        }
        .tab-btn:hover {
            background: rgba(255,255,255,0.1);
        }
        .tab-btn.active {
            background: rgba(79, 172, 254, 0.2);
            border-color: #4facfe;
            color: #fff;
            box-shadow: 0 0 20px rgba(79, 172, 254, 0.15);
        }
        .tab-content {
            display: none;
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            padding: 30px;
            border: 1px solid rgba(79, 172, 254, 0.15);
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        }
        .tab-content.active {
            display: block;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            font-weight: 600;
            margin-bottom: 6px;
            color: #b0c4de;
            font-size: 0.95rem;
        }
        input[type="text"] {
            width: 100%;
            padding: 12px 16px;
            background: rgba(255,255,255,0.07);
            border: 2px solid #2a3f5f;
            border-radius: 12px;
            color: #f0f0f0;
            font-size: 1rem;
            transition: all 0.3s ease;
            outline: none;
        }
        input[type="text"]:focus {
            border-color: #4facfe;
            background: rgba(255,255,255,0.12);
            box-shadow: 0 0 20px rgba(79, 172, 254, 0.15);
        }
        .checkbox-group {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin: 10px 0 20px 0;
        }
        .checkbox-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            background: rgba(255,255,255,0.04);
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.06);
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .checkbox-item:hover {
            background: rgba(255,255,255,0.08);
            border-color: rgba(79, 172, 254, 0.3);
        }
        .checkbox-item input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: #4facfe;
            cursor: pointer;
        }
        .checkbox-item label {
            margin: 0;
            cursor: pointer;
            font-weight: 500;
            font-size: 0.95rem;
            color: #d0d8ec;
        }
        .checkbox-item.disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }
        .checkbox-item.disabled input {
            cursor: not-allowed;
        }
        .btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #4facfe, #00f2fe);
            border: none;
            border-radius: 12px;
            color: #1a1a2e;
            font-size: 1.2rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(79, 172, 254, 0.3);
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .loading {
            display: none;
            text-align: center;
            padding: 30px;
            font-size: 1.1rem;
            color: #4facfe;
        }
        .loading.active {
            display: block;
        }
        .spinner {
            display: inline-block;
            width: 50px;
            height: 50px;
            border: 4px solid rgba(79, 172, 254, 0.15);
            border-top-color: #4facfe;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-bottom: 15px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .results-box {
            margin-top: 25px;
            display: none;
        }
        .results-box.active {
            display: block;
        }
        .results-table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(0,0,0,0.3);
            border-radius: 12px;
            overflow: hidden;
        }
        .results-table th {
            background: rgba(79, 172, 254, 0.15);
            padding: 12px 16px;
            text-align: right;
            font-weight: 600;
            color: #b0c4de;
            border-bottom: 2px solid rgba(79, 172, 254, 0.1);
        }
        .results-table td {
            padding: 10px 16px;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            color: #e0e8f0;
        }
        .results-table tr:hover td {
            background: rgba(79, 172, 254, 0.05);
        }
        .results-table .type-cell {
            color: #8ab4ff;
            font-weight: 500;
        }
        .results-table .value-cell {
            font-family: 'Consolas', monospace;
            font-size: 0.9rem;
        }
        .error {
            background: rgba(255, 70, 70, 0.15);
            border: 1px solid rgba(255, 70, 70, 0.3);
            padding: 16px;
            border-radius: 12px;
            color: #ff6b6b;
            margin: 10px 0;
            display: none;
        }
        .error.active {
            display: block;
        }
        .stats {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            justify-content: center;
            margin: 15px 0;
        }
        .stat-card {
            background: rgba(255,255,255,0.04);
            padding: 8px 16px;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.06);
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.9rem;
        }
        .stat-card .count {
            font-weight: 700;
            color: #4facfe;
            font-size: 1.2rem;
        }
        .history-list {
            margin-top: 15px;
        }
        .history-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            background: rgba(255,255,255,0.04);
            border-radius: 10px;
            margin-bottom: 8px;
            border: 1px solid rgba(255,255,255,0.06);
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .history-item:hover {
            background: rgba(255,255,255,0.08);
            border-color: rgba(79, 172, 254, 0.2);
        }
        .history-item .info {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .history-item .info span {
            color: #a0b4c8;
        }
        .history-item .info .url {
            color: #4facfe;
            font-weight: 500;
        }
        .history-item .badge {
            background: rgba(79, 172, 254, 0.15);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            color: #8ab4ff;
        }
        .detail-view {
            margin-top: 20px;
            display: none;
        }
        .detail-view.active {
            display: block;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.06);
            color: #6a8aaa;
            font-size: 0.85rem;
        }
        @media (max-width: 700px) {
            .container { padding: 0; }
            .tab-btn { padding: 10px 16px; font-size: 0.9rem; }
            .checkbox-group { grid-template-columns: repeat(2, 1fr); }
            .history-item { flex-direction: column; align-items: flex-start; gap: 8px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🕷️ Minouta Web Scraper</h1>
            <p>استخراج اطلاعات از وب‌سایت‌ها با یک کلیک</p>
        </div>

        <div class="tabs">
            <button class="tab-btn active" data-tab="scrape">🔍 اسکرپ جدید</button>
            <button class="tab-btn" data-tab="history">📋 تاریخچه</button>
        </div>

        <!-- تب اسکرپ -->
        <div id="tab-scrape" class="tab-content active">
            <div id="error" class="error"></div>
            <form id="scrapeForm">
                <div class="form-group">
                    <label>🌐 آدرس وب‌سایت</label>
                    <input type="text" id="urlInput" placeholder="مثلاً: hamzehalizadeh.ir" required>
                </div>

                <div class="form-group">
                    <label>🔍 انتخاب داده‌ها برای استخراج</label>
                    <div class="checkbox-group">
                        <div class="checkbox-item">
                            <input type="checkbox" id="chkMobile" checked>
                            <label for="chkMobile">📱 موبایل</label>
                        </div>
                        <div class="checkbox-item">
                            <input type="checkbox" id="chkLandline" checked>
                            <label for="chkLandline">🏠 ثابت</label>
                        </div>
                        <div class="checkbox-item">
                            <input type="checkbox" id="chkEmail" checked>
                            <label for="chkEmail">✉️ ایمیل</label>
                        </div>
                        <div class="checkbox-item">
                            <input type="checkbox" id="chkInstagram" checked>
                            <label for="chkInstagram">📸 اینستاگرام</label>
                        </div>
                        <div class="checkbox-item">
                            <input type="checkbox" id="chkYoutube" checked>
                            <label for="chkYoutube">▶️ یوتیوب</label>
                        </div>
                        <div class="checkbox-item disabled">
                            <input type="checkbox" id="chkLinks" disabled>
                            <label for="chkLinks">🔗 لینک (غیرفعال)</label>
                        </div>
                    </div>
                </div>

                <button type="submit" class="btn" id="submitBtn">🚀 شروع اسکرپ</button>
            </form>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <div>در حال اسکرپ کردن... لطفاً صبر کنید</div>
            </div>

            <div class="results-box" id="resultsBox">
                <div class="stats" id="stats"></div>
                <table class="results-table" id="resultTable">
                    <thead>
                        <tr>
                            <th>نوع</th>
                            <th>مقدار</th>
                        </tr>
                    </thead>
                    <tbody id="resultBody"></tbody>
                </table>
            </div>
        </div>

        <!-- تب تاریخچه -->
        <div id="tab-history" class="tab-content">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h2 style="color: #b0c4de;">📋 اسکرپ‌های قبلی</h2>
                <button class="btn" style="width: auto; padding: 8px 20px; font-size: 0.9rem;" id="refreshHistory">🔄 بارگذاری مجدد</button>
            </div>
            <div id="historyList" class="history-list">
                <div style="text-align:center; color:#6a8aaa; padding: 20px;">در حال بارگذاری...</div>
            </div>
            <div class="detail-view" id="historyDetail">
                <h3 style="color: #b0c4de; margin-bottom: 10px;">📄 جزئیات اسکرپ</h3>
                <div id="historyDetailContent"></div>
            </div>
        </div>

        <div class="footer">
            ⚡ طراحی شده توسط arman hajizadeh
        </div>
    </div>

    <script>
        const API_BASE = window.location.origin;

        // مدیریت تب‌ها
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
                document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
                if (btn.dataset.tab === 'history') {
                    loadHistory();
                }
            });
        });

        // فرم اسکرپ
        const form = document.getElementById('scrapeForm');
        const urlInput = document.getElementById('urlInput');
        const submitBtn = document.getElementById('submitBtn');
        const loading = document.getElementById('loading');
        const resultsBox = document.getElementById('resultsBox');
        const resultBody = document.getElementById('resultBody');
        const stats = document.getElementById('stats');
        const errorDiv = document.getElementById('error');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const url = urlInput.value.trim();
            if (!url) {
                showError('لطفاً آدرس وب‌سایت را وارد کنید.');
                return;
            }

            const extractMobile = document.getElementById('chkMobile').checked;
            const extractLandline = document.getElementById('chkLandline').checked;
            const extractEmail = document.getElementById('chkEmail').checked;
            const extractInstagram = document.getElementById('chkInstagram').checked;
            const extractYoutube = document.getElementById('chkYoutube').checked;

            submitBtn.disabled = true;
            loading.classList.add('active');
            resultsBox.classList.remove('active');
            errorDiv.classList.remove('active');

            try {
                const response = await fetch(`${API_BASE}/scrape`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        urls: [url],
                        extract_mobile: extractMobile,
                        extract_landline: extractLandline,
                        extract_email: extractEmail,
                        extract_links: false,
                        extract_instagram: extractInstagram,
                        extract_youtube: extractYoutube,
                        save_history: true
                    })
                });

                const data = await response.json();

                if (!response.ok) {
                    showError(`خطا: ${data.detail || 'مشکل در ارتباط با سرور'}`);
                    return;
                }

                if (data.results && data.results.length > 0) {
                    const result = data.results[0];
                    if (result.error) {
                        showError(`خطا: ${result.error}`);
                        return;
                    }
                    displayResults(result);
                } else {
                    showError('نتیجه‌ای دریافت نشد.');
                }

            } catch (err) {
                showError(`خطا در ارتباط با سرور: ${err.message}`);
            } finally {
                submitBtn.disabled = false;
                loading.classList.remove('active');
            }
        });

        function displayResults(result) {
            const rows = [];
            const categories = [
                { key: 'mobiles', label: '📱 موبایل' },
                { key: 'landlines', label: '🏠 ثابت' },
                { key: 'emails', label: '✉️ ایمیل' },
                { key: 'instagram', label: '📸 اینستاگرام' },
                { key: 'youtube', label: '▶️ یوتیوب' }
            ];

            let total = 0;
            let statsHTML = '';

            categories.forEach(cat => {
                const values = result[cat.key] || [];
                const count = values.length;
                total += count;
                const icon = cat.label.split(' ')[0];
                statsHTML += `<div class="stat-card">${icon} <span class="count">${count}</span> ${cat.label.split(' ').slice(1).join(' ')}</div>`;

                if (count === 0) {
                    rows.push({ type: cat.label, value: '—' });
                } else {
                    values.forEach(v => {
                        rows.push({ type: cat.label, value: v });
                    });
                }
            });

            stats.innerHTML = statsHTML;

            resultBody.innerHTML = '';
            rows.forEach(row => {
                const tr = document.createElement('tr');
                const td1 = document.createElement('td');
                td1.className = 'type-cell';
                td1.textContent = row.type;
                const td2 = document.createElement('td');
                td2.className = 'value-cell';
                td2.textContent = row.value;
                tr.appendChild(td1);
                tr.appendChild(td2);
                resultBody.appendChild(tr);
            });

            resultsBox.classList.add('active');
        }

        function showError(msg) {
            errorDiv.textContent = '❌ ' + msg;
            errorDiv.classList.add('active');
        }

        // بارگذاری تاریخچه
        async function loadHistory() {
            const listEl = document.getElementById('historyList');
            try {
                const response = await fetch(`${API_BASE}/history?limit=50`);
                if (!response.ok) throw new Error('خطا در دریافت تاریخچه');
                const data = await response.json();

                if (!data || data.length === 0) {
                    listEl.innerHTML = '<div style="text-align:center; color:#6a8aaa; padding: 20px;">هیچ اسکرپی ثبت نشده است.</div>';
                    return;
                }

                let html = '';
                data.forEach(item => {
                    const mobCount = (item.mobiles || []).length;
                    const emailCount = (item.emails || []).length;
                    const instaCount = (item.instagram || []).length;
                    const ytCount = (item.youtube || []).length;
                    const time = new Date(item.timestamp).toLocaleString('fa-IR');
                    html += `
                        <div class="history-item" data-id="${item.id}">
                            <div class="info">
                                <span class="url">${item.url}</span>
                                <span>🕒 ${time}</span>
                                <span>📱 ${mobCount}</span>
                                <span>✉️ ${emailCount}</span>
                                <span>📸 ${instaCount}</span>
                                <span>▶️ ${ytCount}</span>
                            </div>
                            <span class="badge">مشاهده جزئیات</span>
                        </div>
                    `;
                });
                listEl.innerHTML = html;

                // رویداد کلیک برای نمایش جزئیات
                document.querySelectorAll('.history-item').forEach(el => {
                    el.addEventListener('click', () => {
                        const id = el.dataset.id;
                        loadHistoryDetail(id);
                    });
                });

            } catch (err) {
                listEl.innerHTML = `<div style="text-align:center; color:#ff6b6b; padding: 20px;">❌ ${err.message}</div>`;
            }
        }

        async function loadHistoryDetail(id) {
            const detailDiv = document.getElementById('historyDetail');
            const contentDiv = document.getElementById('historyDetailContent');
            try {
                const response = await fetch(`${API_BASE}/history/${id}`);
                if (!response.ok) throw new Error('خطا در دریافت جزئیات');
                const item = await response.json();

                const categories = [
                    { key: 'mobiles', label: '📱 موبایل' },
                    { key: 'landlines', label: '🏠 ثابت' },
                    { key: 'emails', label: '✉️ ایمیل' },
                    { key: 'instagram', label: '📸 اینستاگرام' },
                    { key: 'youtube', label: '▶️ یوتیوب' }
                ];

                let html = `<div style="margin-bottom:10px; color:#a0b4c8;">📌 <strong>${item.url}</strong>  —  🕒 ${new Date(item.timestamp).toLocaleString('fa-IR')}</div>`;
                html += `<table class="results-table" style="margin-top:10px;">
                            <thead><tr><th>نوع</th><th>مقدار</th></tr></thead><tbody>`;
                let found = false;
                categories.forEach(cat => {
                    const values = item[cat.key] || [];
                    if (values.length === 0) {
                        html += `<tr><td class="type-cell">${cat.label}</td><td class="value-cell">—</td></tr>`;
                    } else {
                        found = true;
                        values.forEach(v => {
                            html += `<tr><td class="type-cell">${cat.label}</td><td class="value-cell">${v}</td></tr>`;
                        });
                    }
                });
                if (!found) {
                    html += `<tr><td colspan="2" style="text-align:center; color:#6a8aaa;">داده‌ای یافت نشد</td></tr>`;
                }
                html += `</tbody></table>`;
                contentDiv.innerHTML = html;
                detailDiv.classList.add('active');

                // اسکرول به قسمت جزئیات
                detailDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });

            } catch (err) {
                contentDiv.innerHTML = `<div style="color:#ff6b6b;">❌ ${err.message}</div>`;
                detailDiv.classList.add('active');
            }
        }

        // بارگذاری تاریخچه هنگام کلیک روی تب
        document.getElementById('refreshHistory').addEventListener('click', loadHistory);

        // Normalize URL
        urlInput.addEventListener('blur', function() {
            let val = this.value.trim();
            if (val && !val.startsWith('http://') && !val.startsWith('https://')) {
                this.value = 'https://' + val;
            }
        });

        // بارگذاری اولیه تاریخچه اگر تب فعال باشه (فعلاً غیرفعال)
    </script>
</body>
</html>
"""

# ============================================================
# 🌐 سرور وب (FastAPI) با CORS و رابط کاربری
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

@app.get("/", response_class=HTMLResponse)
def root():
    return HTML_PAGE

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
                        extract_links=False,
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