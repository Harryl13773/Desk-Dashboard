function doGet(e) {
  var calendar = CalendarApp.getDefaultCalendar();
  var now = new Date();
  var oneWeekFromNow = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);

  var events = calendar.getEvents(now, oneWeekFromNow);
  var results = [];

  var maxEvents = Math.min(events.length, 10);
  for (var i = 0; i < maxEvents; i++) {
    var event = events[i];
    results.push({
      title: event.getTitle(),
      start: event.getStartTime().toISOString(),
    });
  }

  return ContentService.createTextOutput(JSON.stringify(results)).setMimeType(
    ContentService.MimeType.JSON,
  );
}
