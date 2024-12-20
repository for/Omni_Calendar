import os, json, sys, requests
from datetime import datetime, timedelta
from PyQt6.QtWidgets import *
from PyQt6.QtCore import QDate, QDateTime, Qt, QThread, pyqtSignal, QTime
from PyQt6.QtGui import QTextCharFormat, QColor, QPalette

class ErrorHandler:
    @staticmethod
    def show_error(message): QMessageBox.critical(None, "Error", message)

class DataValidator:
    @staticmethod
    def validate_entry(entry): return bool(entry.strip())
    @staticmethod
    def validate_event(datetime_str, description): return bool(datetime_str and description.strip())

class LLMQuery(QThread):
    result_ready = pyqtSignal(str)
    def __init__(self, query):
        super().__init__(); self.query = query
    def run(self):
        try: self.result_ready.emit(self.query_llm(self.query))
        except Exception as e: ErrorHandler.show_error(f"Error analyzing events: {str(e)}")
    
    def query_llm(self, query):
        api_url = "http://127.0.0.1:1234/v1/completions"
        system_prompt = """You are a helpful diary assistant that analyzes personal entries and events. 
        Analyze the provided diary entries and calendar events to:
        1. Identify patterns and connections between entries
        2. Highlight important upcoming events
        3. Summarize recent activities and their significance
        4. Suggest potential actions based on the entries
        Format your response in clear sections:
        - Recent Activity Summary
        - Patterns & Insights
        - Important Upcoming Events
        - Suggested Actions"""

        context = self.format_rag_context(query["context"])
        user_prompt = f"""
        Timeline Context:
        Current Date and Time: {context['current_datetime']}
        Date Range: {context['date_range']['start']} to {context['date_range']['end']}
        Recent Diary Entries:
        {context['formatted_diary_entries']}
        Calendar Events:
        {context['formatted_calendar_events']}
        Please provide an analysis based on this information.
        """
        payload = {"model": "llama-3.2-1b-instruct", "prompt": f"{system_prompt}\n\n{user_prompt}",
            "max_tokens": 500, "temperature": 0.7, "top_p": 0.95, "n": 1, "repeat_penalty": 1.1, "stop": ["End of Analysis", "End of Summary"]}
        headers = {"Content-Type": "application/json"}
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30); response.raise_for_status(); result = response.json()
            return result["choices"][0].get("text", "No analysis available").strip() if "choices" in result and result["choices"] else "No analysis available"
        except requests.exceptions.RequestException as e: raise Exception(f"Failed to connect to LLM: {str(e)}")
        except Exception as e: raise Exception(f"Error processing LLM response: {str(e)}")
    
    def format_rag_context(self, context):
        """Format the context for better RAG processing"""
        formatted_diary_entries = "\n".join([
            f"[{entry['datetime']}] {entry['content'][:200]}{'...' if len(entry['content']) > 200 else ''}"
            for entry in sorted(context['recent_events'], key=lambda x: x['datetime'])])
        formatted_calendar_events = "\n".join([
            f"[{event['datetime']}] {event['event']}"
            for event in sorted(context['upcoming_events'], key=lambda x: x['datetime'])])
        return {"current_datetime": context['current_datetime'], "date_range": context['date_range'],
            "formatted_diary_entries": formatted_diary_entries, "formatted_calendar_events": formatted_calendar_events}

class DiaryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Diary with RAG")
        self.setGeometry(100, 100, 1000, 800)
        self.setup_ui()
        self.diary_entries = self.load_json("diary_entries.json")
        self.calendar_events = self.load_json("calendar_events.json")
        self.highlight_dates()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout()
        self.central_widget.setLayout(self.layout)
        
        self.calendar = QCalendarWidget() # Calendar
        self.calendar.setGridVisible(True)
        self.calendar.selectionChanged.connect(self.load_selected_date_content)
        self.layout.addWidget(self.calendar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal) # Splitter for diary and events
        self.diary_widget = self.create_diary_widget()
        self.events_widget = self.create_events_widget()
        self.splitter.addWidget(self.diary_widget)
        self.splitter.addWidget(self.events_widget)
        self.layout.addWidget(self.splitter)
        self.fetch_button = QPushButton("Analyze Events and Patterns") # Analysis section
        self.fetch_button.clicked.connect(self.fetch_closest_events)
        self.layout.addWidget(self.fetch_button)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.analysis_label = QLabel()
        self.analysis_label.setWordWrap(True)
        self.scroll_area.setWidget(self.analysis_label)
        self.scroll_area.setMinimumHeight(150)
        self.layout.addWidget(self.scroll_area)
        self.apply_theme()

    def create_diary_widget(self):
        diary_widget = QWidget(); diary_layout = QVBoxLayout(); diary_widget.setLayout(diary_layout)
        diary_layout.addWidget(QLabel("Diary Entry:")); self.diary_entry = QTextEdit(); self.diary_entry.setMinimumHeight(150); diary_layout.addWidget(self.diary_entry)
        save_button = QPushButton("Save Entry"); save_button.clicked.connect(self.save_diary_entry); diary_layout.addWidget(save_button)
        return diary_widget

    def create_events_widget(self):
        events_widget = QWidget(); events_layout = QVBoxLayout(); events_widget.setLayout(events_layout)
        events_layout.addWidget(QLabel("Events:")); self.events_display = QTextEdit(); self.events_display.setReadOnly(True); self.events_display.setMinimumHeight(150)
        events_layout.addWidget(self.events_display); event_form_layout = QFormLayout(); self.event_datetime_input = QDateTimeEdit()
        self.event_datetime_input.setDisplayFormat("yyyy-MM-dd HH:mm"); self.event_datetime_input.setCalendarPopup(True)
        self.event_description_input = QLineEdit(); self.event_description_input.setPlaceholderText("Event Description")
        event_form_layout.addRow("Event Date & Time:", self.event_datetime_input); event_form_layout.addRow("Event Description:", self.event_description_input)
        events_layout.addLayout(event_form_layout)
        save_event_button = QPushButton("Save Event"); save_event_button.clicked.connect(self.save_calendar_event); events_layout.addWidget(save_event_button)
        return events_widget

    def apply_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30)); palette.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
        palette.setColor(QPalette.ColorRole.Base, QColor(45, 45, 45)); palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255)); palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Text, QColor(230, 230, 230)); palette.setColor(QPalette.ColorRole.Button, QColor(50, 50, 50))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(230, 230, 230)); palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 255))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(186, 85, 211)); palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        self.setPalette(palette)
        self.setStyleSheet("""
            QWidget {border-radius: 10px; background-color: #1E1E1E; color: #E6E6E6;}
            QPushButton {background-color: #3A3A3A; color: #E6E6E6; border: 2px solid #BA55D3; border-radius: 10px; padding: 5px;}
            QPushButton:hover {background-color: #BA55D3; color: #1E1E1E;}
            QTextEdit, QLineEdit, QDateTimeEdit {background-color: #2D2D2D; color: #E6E6E6; border: 2px solid #BA55D3; border-radius: 10px; padding: 5px;}
            QLabel {color: #E6E6E6;}
            QCalendarWidget QToolButton {background-color: #3A3A3A; color: #E6E6E6; border: none; border-radius: 5px;}
            QCalendarWidget QToolButton:hover {background-color: #BA55D3; color: #1E1E1E;}
            QCalendarWidget QAbstractItemView {background-color: #2D2D2D; selection-background-color: #BA55D3; selection-color: #1E1E1E; border-radius: 5px;}
        """)

    def load_json(self, filename):
        try:
            if os.path.exists(filename):
                with open(filename, "r", encoding='utf-8') as file: return json.load(file)
        except Exception as e: ErrorHandler.show_error(f"Error loading {filename}: {e}")
        return {}

    def save_json(self, data, filename):
        try:
            with open(filename, "w", encoding='utf-8') as file: json.dump(data, file, ensure_ascii=False, indent=2)
        except Exception as e: ErrorHandler.show_error(f"Error saving {filename}: {e}")

    def highlight_dates(self):
        diary_format = QTextCharFormat(); diary_format.setBackground(QColor(173, 216, 230))
        event_format = QTextCharFormat(); event_format.setBackground(QColor(144, 238, 144))
        both_format = QTextCharFormat(); both_format.setBackground(QColor(230, 230, 250))
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        for datetime_str in set(list(self.diary_entries.keys()) + list(self.calendar_events.keys())):
            try:
                date_str = datetime_str.split(" ")[0]
                date = QDate.fromString(date_str, "yyyy-MM-dd")
                has_diary = datetime_str in self.diary_entries
                has_event = datetime_str in self.calendar_events
                self.calendar.setDateTextFormat(date, both_format if has_diary and has_event else diary_format if has_diary else event_format)
            except Exception as e: ErrorHandler.show_error(f"Error highlighting date {datetime_str}: {e}")

    def load_selected_date_content(self):
        date = self.calendar.selectedDate().toString("yyyy-MM-dd")
        current_time = QTime.currentTime().toString("HH:mm")
        datetime_str = f"{date} {current_time}"
        diary_entries_for_date = [f"{dt}: {entry}" for dt, entry in self.diary_entries.items()
            if dt.startswith(date)]
        events_for_date = [f"{dt}: {event}" for dt, event in self.calendar_events.items()
            if dt.startswith(date)]
        self.diary_entry.setText("\n".join(diary_entries_for_date) if diary_entries_for_date
            else "No diary entries for this date.")
        self.events_display.setText("\n".join(events_for_date) if events_for_date
            else "No events for this date.")
        self.event_datetime_input.setDateTime(QDateTime.fromString(datetime_str, "yyyy-MM-dd HH:mm"))

    def save_diary_entry(self):
        datetime_str = self.event_datetime_input.dateTime().toString("yyyy-MM-dd HH:mm")
        entry = self.diary_entry.toPlainText()
        if DataValidator.validate_entry(entry):
            self.diary_entries[datetime_str] = entry
            self.save_json(self.diary_entries, "diary_entries.json")
            self.highlight_dates()
            QMessageBox.information(self, "Success", "Diary entry saved successfully.")
        else: ErrorHandler.show_error("Diary entry cannot be empty.")

    def save_calendar_event(self):
        datetime_str = self.event_datetime_input.dateTime().toString("yyyy-MM-dd HH:mm")
        description = self.event_description_input.text().strip()
        if DataValidator.validate_event(datetime_str, description):
            self.calendar_events[datetime_str] = description
            self.save_json(self.calendar_events, "calendar_events.json")
            self.highlight_dates()
            self.event_description_input.clear()
            QMessageBox.information(self, "Success", "Event saved successfully.")
        else: ErrorHandler.show_error("Event description cannot be empty.")

    def fetch_closest_events(self):
        current_datetime = QDateTime.currentDateTime()
        context = self.prepare_rag_context(current_datetime)
        query = {"context": context}
        self.progress_bar.setVisible(True); self.progress_bar.setRange(0, 0)
        self.llm_thread = LLMQuery(query); self.llm_thread.result_ready.connect(self.display_analysis_result); self.llm_thread.start()

    def display_analysis_result(self, result): self.progress_bar.setVisible(False); self.analysis_label.setText(result)
    def prepare_rag_context(self, current_datetime):
        context = {
            "current_datetime": current_datetime.toString("yyyy-MM-dd HH:mm:ss"), "recent_events": [], "upcoming_events": [],
            "date_range": {"start": (current_datetime.addDays(-7)).toString("yyyy-MM-dd"), "end": (current_datetime.addDays(14)).toString("yyyy-MM-dd")}}
        for datetime_str, entry in self.diary_entries.items(): # Process diary entries with more context
            entry_datetime = QDateTime.fromString(datetime_str, "yyyy-MM-dd HH:mm")
            days_difference = entry_datetime.daysTo(current_datetime)
            if -7 <= days_difference <= 0:  # Past week entries
                context["recent_events"].append({"datetime": datetime_str, "content": entry, "days_ago": abs(days_difference)})
        for datetime_str, event in self.calendar_events.items(): # Process calendar events with more context
            event_datetime = QDateTime.fromString(datetime_str, "yyyy-MM-dd HH:mm")
            days_difference = current_datetime.daysTo(event_datetime)
            if 0 <= days_difference <= 14: context["upcoming_events"].append({"datetime": datetime_str, "event": event, "days_until": days_difference, "is_urgent": days_difference <= 3})
        context["recent_events"].sort(key=lambda x: x["datetime"]); context["upcoming_events"].sort(key=lambda x: x["datetime"]) # Sort entries chronologically
        return context

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DiaryApp()
    window.show()
    sys.exit(app.exec())