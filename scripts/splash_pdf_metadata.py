"""Read only an event's result-header date, never a record or PDF footer date."""
from datetime import date
import re


def event_date(text, label, meet):
    pattern = (r'^\s*(\d{1,2})([./-])(\d{1,2})\2(\d{4}|\d{2})\.?'
               r'\s*(?:г\.\s*)?(?:-\s*\d{1,2}:\d{2})?\s+' + re.escape(label) + r'\b')
    found=set()
    for m in re.finditer(pattern,text,re.M):
        day,_,month,year=m.groups()
        years=[int(year)]if len(year)==4 else [y for y in range(int(meet['start_date'][:4]),int(meet['end_date'][:4])+1)if y%100==int(year)]
        for y in years:
            try:value=str(date(y,int(month),int(day)))
            except ValueError:continue
            if meet['start_date']<=value<=meet['end_date']:found.add(value)
    return next(iter(found))if len(found)==1 else None
