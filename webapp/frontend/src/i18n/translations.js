// ParkSentry i18n catalog. English is the source and the fallback.
// Acronyms / proper nouns (EPI, RMSE, Mappls, FastAPI, ParkSentry, DBSCAN, CSV,
// React, Node) are intentionally kept in Latin script across all languages.

export const LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'hi', name: 'हिन्दी' },
  { code: 'kn', name: 'ಕನ್ನಡ' },
];

export const DEFAULT_LANG = 'en';

export const STRINGS = {
  // ----------------------------------------------------------------- English
  en: {
    'lang.label': 'Language',
    'app.title': 'ParkSentry — Parking Congestion Intelligence',

    'header.suffix': '— Parking-Induced Congestion Intelligence',
    'header.subtitle':
      'Detect illegal-parking hotspots · quantify congestion impact · target enforcement. Data: Bengaluru police parking violations.',
    'header.live': 'Live · {start} → {end}',
    'header.connecting': 'Connecting…',
    'header.offline': 'Service offline',
    'header.connected': 'Data service connected',
    'header.errorBanner':
      'Could not reach the data service: {err}. Is the gateway running on :8000 and FastAPI on :8001?',
    'footer.text': 'ParkSentry · React + Node/Express + FastAPI · Mappls maps',

    'tabs.map': 'Priority Map',
    'tabs.table': 'Priority List',
    'tabs.forecast': 'Live Forecaster',
    'tabs.model': 'Model & EDA',

    'kpi.cleanViolations': 'Clean violations',
    'kpi.priorityCellsZones': 'Priority cells / zones',
    'kpi.bestModel': 'Best model',
    'kpi.bestModelHint': 'RMSE {rmse} vs baseline {baseline}',
    'kpi.capture5': 'Top-5% capture',
    'kpi.capture5Hint':
      'Share of all violations caught by patrolling the top 5% predicted slots',
    'kpi.capture1': 'Top-1% capture',
    'kpi.loading': 'loading…',

    'map.hint':
      'Each dot is a ~150 m enforcement cell (a specific road stretch), sized & coloured by its Enforcement Priority Index (EPI). Click a dot for its rank, station and predicted volume.',
    'map.topN': 'Top-N cells',
    'map.peakBlock': 'Peak time block',
    'map.policeStation': 'Police station',
    'map.filterStations': 'Filter stations…',
    'map.stations': '{count} stations',
    'map.clear': 'clear',
    'map.cellsShown': '{count} cells shown',
    'map.popup.rank': 'Rank #{rank}',
    'map.popup.perDay': '~{n}/day',

    'mapview.legendTitle': 'Enforcement Priority Index',
    'mapview.low': 'Low',
    'mapview.high': 'High',
    'mapview.needKey': 'Maps need a Mappls key',
    'mapview.couldNotLoad': 'Map could not load',
    'mapview.needKeyBody':
      'The data, rankings, forecaster and charts all work without a key — only the interactive map needs Mappls credentials.',
    'mapview.step1': 'Create an app at apps.mappls.com and copy the keys.',
    'mapview.step2':
      'Set MAPPLS_CLIENT_ID + MAPPLS_CLIENT_SECRET (or MAPPLS_MAP_SDK_KEY) in the gateway environment.',
    'mapview.step3': 'Ensure the Map SDK is enabled in the console, then reload.',
    'mapview.loading': 'Loading map…',

    'forecast.title': 'Forecast parking-violation risk for any zone / time',
    'forecast.hint':
      "Rebuilds the model's features causally and scores every known cell on demand (Python FastAPI + the deployable Forecaster). First run loads the model, so it can take a few seconds.",
    'forecast.date': 'Date',
    'forecast.timeBlock': 'Time block',
    'forecast.topCells': 'Top cells:',
    'forecast.scoring': 'Scoring…',
    'forecast.run': 'Run forecast',
    'forecast.empty':
      'Pick a date and time block, then run a forecast to see the busiest predicted cells on the map.',
    'forecast.colNum': '#',
    'forecast.colPred': 'Pred viol',
    'forecast.colCell': 'Cell',
    'forecast.colStation': 'Police station',
    'forecast.popup.cell': 'cell {cell}',
    'forecast.popup.viol': '~{n} viol',

    'model.comparisonTitle': 'Model comparison',
    'model.comparisonHint':
      'Five challengers vs the historical-mean baseline, evaluated on a temporal hold-out. Selected on RMSE + top-K capture — the metric enforcement cares about.',
    'model.evidenceTitle': 'Evidence the forecast can be trusted',
    'plot.model_capture_curve.png': 'Enforcement-efficiency curve',
    'plot.model_feature_importance.png': 'What the model keys on',
    'plot.model_comparison.png': 'Error vs efficiency',
    'plot.hotspot_map.png': 'Density & priority hotspots',
    'plot.eda_temporal.png': 'When violations happen',
    'plot.eda_violation_types.png': 'Violation mix',
    'plot.eda_vehicle_trend.png': 'Vehicles & monthly trend',
    'plot.eda_impact_dist.png': 'Impact score distribution',

    'table.title': 'Enforcement Priority Index — ranked cells',
    'table.downloadCsv': 'Download CSV',
    'table.hint':
      'Primary targeting unit. {count} cells ranked by EPI — the smooth, forecast-driven priority score that decides where the next patrol goes.',
    'table.col.rank': 'Rank',
    'table.col.epi': 'EPI',
    'table.col.predDay': 'Pred/day',
    'table.col.actualDay': 'Actual/day',
    'table.col.impactViol': 'Impact/viol',
    'table.col.events': 'Events',
    'table.col.peakBlock': 'Peak block',
    'table.col.policeStation': 'Police station',
    'table.col.junction': 'Junction',
    'table.zonesToggle': 'Secondary: DBSCAN density zones (beat-level grouping)',
  },

  // ------------------------------------------------------------------- Hindi
  hi: {
    'lang.label': 'भाषा',
    'app.title': 'ParkSentry — पार्किंग भीड़भाड़ इंटेलिजेंस',

    'header.suffix': '— पार्किंग-जनित भीड़भाड़ इंटेलिजेंस',
    'header.subtitle':
      'अवैध पार्किंग के हॉटस्पॉट पहचानें · भीड़भाड़ प्रभाव मापें · प्रवर्तन लक्षित करें। डेटा: बेंगलुरु पुलिस पार्किंग उल्लंघन।',
    'header.live': 'लाइव · {start} → {end}',
    'header.connecting': 'कनेक्ट हो रहा है…',
    'header.offline': 'सेवा ऑफ़लाइन',
    'header.connected': 'डेटा सेवा कनेक्टेड',
    'header.errorBanner':
      'डेटा सेवा तक नहीं पहुँच सका: {err}। क्या गेटवे :8000 पर और FastAPI :8001 पर चल रहा है?',
    'footer.text': 'ParkSentry · React + Node/Express + FastAPI · Mappls मानचित्र',

    'tabs.map': 'प्राथमिकता मानचित्र',
    'tabs.table': 'प्राथमिकता सूची',
    'tabs.forecast': 'लाइव पूर्वानुमान',
    'tabs.model': 'मॉडल और EDA',

    'kpi.cleanViolations': 'साफ़ किए गए उल्लंघन रिकॉर्ड',
    'kpi.priorityCellsZones': 'प्राथमिकता सेल / ज़ोन',
    'kpi.bestModel': 'सर्वश्रेष्ठ मॉडल',
    'kpi.bestModelHint': 'RMSE {rmse} बनाम बेसलाइन {baseline}',
    'kpi.capture5': 'टॉप-5% कैप्चर',
    'kpi.capture5Hint':
      'शीर्ष 5% पूर्वानुमानित स्लॉट पर गश्त करके पकड़े गए सभी उल्लंघनों का हिस्सा',
    'kpi.capture1': 'टॉप-1% कैप्चर',
    'kpi.loading': 'लोड हो रहा है…',

    'map.hint':
      'हर बिंदु एक ~150 मी प्रवर्तन सेल है (एक विशिष्ट सड़क खंड), जिसका आकार और रंग उसके Enforcement Priority Index (EPI) से तय होता है। रैंक, थाना और पूर्वानुमानित मात्रा देखने के लिए किसी बिंदु पर क्लिक करें।',
    'map.topN': 'टॉप-N सेल',
    'map.peakBlock': 'व्यस्ततम समय खंड',
    'map.policeStation': 'पुलिस थाना',
    'map.filterStations': 'थाने फ़िल्टर करें…',
    'map.stations': '{count} थाने',
    'map.clear': 'साफ़ करें',
    'map.cellsShown': '{count} सेल दिखाए गए',
    'map.popup.rank': 'रैंक #{rank}',
    'map.popup.perDay': '~{n}/दिन',

    'mapview.legendTitle': 'प्रवर्तन प्राथमिकता सूचकांक',
    'mapview.low': 'कम',
    'mapview.high': 'अधिक',
    'mapview.needKey': 'मानचित्र के लिए Mappls कुंजी चाहिए',
    'mapview.couldNotLoad': 'मानचित्र लोड नहीं हो सका',
    'mapview.needKeyBody':
      'डेटा, रैंकिंग, पूर्वानुमान और चार्ट सब बिना कुंजी के काम करते हैं — केवल इंटरैक्टिव मानचित्र को Mappls क्रेडेंशियल चाहिए।',
    'mapview.step1': 'apps.mappls.com पर एक ऐप बनाएँ और कुंजियाँ कॉपी करें।',
    'mapview.step2':
      'गेटवे एनवायरनमेंट में MAPPLS_CLIENT_ID + MAPPLS_CLIENT_SECRET (या MAPPLS_MAP_SDK_KEY) सेट करें।',
    'mapview.step3': 'सुनिश्चित करें कि कंसोल में Map SDK सक्षम है, फिर रीलोड करें।',
    'mapview.loading': 'मानचित्र लोड हो रहा है…',

    'forecast.title': 'किसी भी ज़ोन / समय के लिए पार्किंग-उल्लंघन जोखिम का पूर्वानुमान',
    'forecast.hint':
      'मॉडल की विशेषताओं को कारण-संगत रूप से पुनर्निर्मित करता है और मांग पर हर ज्ञात सेल को स्कोर करता है (Python FastAPI + डिप्लॉय करने योग्य Forecaster)। पहली बार चलाने पर मॉडल लोड होता है, इसलिए कुछ सेकंड लग सकते हैं।',
    'forecast.date': 'तारीख़',
    'forecast.timeBlock': 'समय खंड',
    'forecast.topCells': 'टॉप सेल:',
    'forecast.scoring': 'स्कोर हो रहा है…',
    'forecast.run': 'पूर्वानुमान चलाएँ',
    'forecast.empty':
      'एक तारीख़ और समय खंड चुनें, फिर मानचित्र पर सबसे व्यस्त पूर्वानुमानित सेल देखने के लिए पूर्वानुमान चलाएँ।',
    'forecast.colNum': '#',
    'forecast.colPred': 'पूर्वा. उल्लंघन',
    'forecast.colCell': 'सेल',
    'forecast.colStation': 'पुलिस थाना',
    'forecast.popup.cell': 'सेल {cell}',
    'forecast.popup.viol': '~{n} उल्लंघन',

    'model.comparisonTitle': 'मॉडल तुलना',
    'model.comparisonHint':
      'ऐतिहासिक-औसत बेसलाइन बनाम पाँच प्रतिस्पर्धी, एक समय-आधारित होल्ड-आउट पर मूल्यांकित। RMSE + टॉप-K कैप्चर पर चयनित — वह मेट्रिक जिसकी प्रवर्तन को परवाह है।',
    'model.evidenceTitle': 'प्रमाण कि पूर्वानुमान पर भरोसा किया जा सकता है',
    'plot.model_capture_curve.png': 'प्रवर्तन-दक्षता वक्र',
    'plot.model_feature_importance.png': 'मॉडल किस पर ध्यान देता है',
    'plot.model_comparison.png': 'त्रुटि बनाम दक्षता',
    'plot.hotspot_map.png': 'घनत्व और प्राथमिकता हॉटस्पॉट',
    'plot.eda_temporal.png': 'उल्लंघन कब होते हैं',
    'plot.eda_violation_types.png': 'उल्लंघन मिश्रण',
    'plot.eda_vehicle_trend.png': 'वाहन और मासिक रुझान',
    'plot.eda_impact_dist.png': 'प्रभाव स्कोर वितरण',

    'table.title': 'प्रवर्तन प्राथमिकता सूचकांक — रैंक की गई सेल',
    'table.downloadCsv': 'CSV डाउनलोड करें',
    'table.hint':
      'मुख्य लक्ष्यीकरण इकाई। {count} सेल EPI के अनुसार रैंक — सहज, पूर्वानुमान-आधारित प्राथमिकता स्कोर जो तय करता है कि अगली गश्त कहाँ जाए।',
    'table.col.rank': 'रैंक',
    'table.col.epi': 'EPI',
    'table.col.predDay': 'पूर्वा./दिन',
    'table.col.actualDay': 'वास्तविक/दिन',
    'table.col.impactViol': 'प्रभाव/उल्लंघन',
    'table.col.events': 'घटनाएँ',
    'table.col.peakBlock': 'व्यस्ततम खंड',
    'table.col.policeStation': 'पुलिस थाना',
    'table.col.junction': 'जंक्शन',
    'table.zonesToggle': 'द्वितीयक: DBSCAN घनत्व ज़ोन (बीट-स्तरीय समूहीकरण)',
  },

  // ----------------------------------------------------------------- Kannada
  kn: {
    'lang.label': 'ಭಾಷೆ',
    'app.title': 'ParkSentry — ಪಾರ್ಕಿಂಗ್ ದಟ್ಟಣೆ ಇಂಟೆಲಿಜೆನ್ಸ್',

    'header.suffix': '— ಪಾರ್ಕಿಂಗ್-ಪ್ರೇರಿತ ದಟ್ಟಣೆ ಇಂಟೆಲಿಜೆನ್ಸ್',
    'header.subtitle':
      'ಅಕ್ರಮ ಪಾರ್ಕಿಂಗ್ ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳನ್ನು ಪತ್ತೆ ಮಾಡಿ · ದಟ್ಟಣೆ ಪರಿಣಾಮವನ್ನು ಅಳೆಯಿರಿ · ಜಾರಿಯನ್ನು ಗುರಿಯಾಗಿಸಿ. ಡೇಟಾ: ಬೆಂಗಳೂರು ಪೊಲೀಸ್ ಪಾರ್ಕಿಂಗ್ ಉಲ್ಲಂಘನೆಗಳು.',
    'header.live': 'ಲೈವ್ · {start} → {end}',
    'header.connecting': 'ಸಂಪರ್ಕಿಸಲಾಗುತ್ತಿದೆ…',
    'header.offline': 'ಸೇವೆ ಆಫ್‌ಲೈನ್',
    'header.connected': 'ಡೇಟಾ ಸೇವೆ ಸಂಪರ್ಕಗೊಂಡಿದೆ',
    'header.errorBanner':
      'ಡೇಟಾ ಸೇವೆಯನ್ನು ತಲುಪಲಾಗಲಿಲ್ಲ: {err}. ಗೇಟ್‌ವೇ :8000 ನಲ್ಲಿ ಮತ್ತು FastAPI :8001 ನಲ್ಲಿ ಚಾಲನೆಯಲ್ಲಿದೆಯೇ?',
    'footer.text': 'ParkSentry · React + Node/Express + FastAPI · Mappls ನಕ್ಷೆಗಳು',

    'tabs.map': 'ಆದ್ಯತಾ ನಕ್ಷೆ',
    'tabs.table': 'ಆದ್ಯತಾ ಪಟ್ಟಿ',
    'tabs.forecast': 'ಲೈವ್ ಮುನ್ಸೂಚಕ',
    'tabs.model': 'ಮಾಡೆಲ್ ಮತ್ತು EDA',

    'kpi.cleanViolations': 'ಶುದ್ಧೀಕರಿಸಿದ ಉಲ್ಲಂಘನೆಗಳು',
    'kpi.priorityCellsZones': 'ಆದ್ಯತಾ ಸೆಲ್‌ಗಳು / ವಲಯಗಳು',
    'kpi.bestModel': 'ಅತ್ಯುತ್ತಮ ಮಾಡೆಲ್',
    'kpi.bestModelHint': 'RMSE {rmse} vs ಬೇಸ್‌ಲೈನ್ {baseline}',
    'kpi.capture5': 'ಟಾಪ್-5% ಕ್ಯಾಪ್ಚರ್',
    'kpi.capture5Hint':
      'ಮುನ್ಸೂಚಿತ ಅಗ್ರ 5% ಸ್ಲಾಟ್‌ಗಳಲ್ಲಿ ಗಸ್ತು ತಿರುಗುವ ಮೂಲಕ ಹಿಡಿಯಲಾದ ಎಲ್ಲಾ ಉಲ್ಲಂಘನೆಗಳ ಪಾಲು',
    'kpi.capture1': 'ಟಾಪ್-1% ಕ್ಯಾಪ್ಚರ್',
    'kpi.loading': 'ಲೋಡ್ ಆಗುತ್ತಿದೆ…',

    'map.hint':
      'ಪ್ರತಿ ಚುಕ್ಕೆ ~150 ಮೀ ಜಾರಿ ಸೆಲ್ (ನಿರ್ದಿಷ್ಟ ರಸ್ತೆ ಭಾಗ), ಅದರ Enforcement Priority Index (EPI) ಆಧಾರದ ಮೇಲೆ ಗಾತ್ರ ಮತ್ತು ಬಣ್ಣ ಹೊಂದಿದೆ. ಶ್ರೇಣಿ, ಠಾಣೆ ಮತ್ತು ಮುನ್ಸೂಚಿತ ಪ್ರಮಾಣಕ್ಕಾಗಿ ಚುಕ್ಕೆಯ ಮೇಲೆ ಕ್ಲಿಕ್ ಮಾಡಿ.',
    'map.topN': 'ಟಾಪ್-N ಸೆಲ್‌ಗಳು',
    'map.peakBlock': 'ಗರಿಷ್ಠ ಸಮಯ ಬ್ಲಾಕ್',
    'map.policeStation': 'ಪೊಲೀಸ್ ಠಾಣೆ',
    'map.filterStations': 'ಠಾಣೆಗಳನ್ನು ಫಿಲ್ಟರ್ ಮಾಡಿ…',
    'map.stations': '{count} ಠಾಣೆಗಳು',
    'map.clear': 'ತೆರವುಗೊಳಿಸಿ',
    'map.cellsShown': '{count} ಸೆಲ್‌ಗಳನ್ನು ತೋರಿಸಲಾಗಿದೆ',
    'map.popup.rank': 'ಶ್ರೇಣಿ #{rank}',
    'map.popup.perDay': '~{n}/ದಿನ',

    'mapview.legendTitle': 'ಜಾರಿ ಆದ್ಯತಾ ಸೂಚ್ಯಂಕ',
    'mapview.low': 'ಕಡಿಮೆ',
    'mapview.high': 'ಹೆಚ್ಚು',
    'mapview.needKey': 'ನಕ್ಷೆಗಳಿಗೆ Mappls ಕೀ ಬೇಕು',
    'mapview.couldNotLoad': 'ನಕ್ಷೆ ಲೋಡ್ ಆಗಲಿಲ್ಲ',
    'mapview.needKeyBody':
      'ಡೇಟಾ, ಶ್ರೇಯಾಂಕಗಳು, ಮುನ್ಸೂಚಕ ಮತ್ತು ಚಾರ್ಟ್‌ಗಳು ಕೀ ಇಲ್ಲದೆ ಕೆಲಸ ಮಾಡುತ್ತವೆ — ಕೇವಲ ಸಂವಾದಾತ್ಮಕ ನಕ್ಷೆಗೆ Mappls ಕ್ರೆಡೆನ್ಷಿಯಲ್ ಬೇಕು.',
    'mapview.step1': 'apps.mappls.com ನಲ್ಲಿ ಒಂದು ಅಪ್ಲಿಕೇಶನ್ ರಚಿಸಿ ಮತ್ತು ಕೀಗಳನ್ನು ನಕಲಿಸಿ.',
    'mapview.step2':
      'ಗೇಟ್‌ವೇ ಪರಿಸರದಲ್ಲಿ MAPPLS_CLIENT_ID + MAPPLS_CLIENT_SECRET (ಅಥವಾ MAPPLS_MAP_SDK_KEY) ಹೊಂದಿಸಿ.',
    'mapview.step3': 'ಕನ್ಸೋಲ್‌ನಲ್ಲಿ Map SDK ಸಕ್ರಿಯವಾಗಿದೆ ಎಂದು ಖಚಿತಪಡಿಸಿಕೊಂಡು ನಂತರ ಮರುಲೋಡ್ ಮಾಡಿ.',
    'mapview.loading': 'ನಕ್ಷೆ ಲೋಡ್ ಆಗುತ್ತಿದೆ…',

    'forecast.title': 'ಯಾವುದೇ ವಲಯ / ಸಮಯಕ್ಕೆ ಪಾರ್ಕಿಂಗ್-ಉಲ್ಲಂಘನೆ ಅಪಾಯದ ಮುನ್ಸೂಚನೆ',
    'forecast.hint':
      'ಮಾಡೆಲ್‌ನ ವೈಶಿಷ್ಟ್ಯಗಳನ್ನು ಕಾರಣಾತ್ಮಕವಾಗಿ ಮರುನಿರ್ಮಿಸಿ ಬೇಡಿಕೆಯ ಮೇರೆಗೆ ಪ್ರತಿ ಪರಿಚಿತ ಸೆಲ್‌ಗೆ ಸ್ಕೋರ್ ನೀಡುತ್ತದೆ (Python FastAPI + ನಿಯೋಜಿಸಬಹುದಾದ Forecaster). ಮೊದಲ ಬಾರಿ ಚಲಾಯಿಸಿದಾಗ ಮಾಡೆಲ್ ಲೋಡ್ ಆಗುತ್ತದೆ, ಆದ್ದರಿಂದ ಕೆಲವು ಸೆಕೆಂಡುಗಳು ತಗಲಬಹುದು.',
    'forecast.date': 'ದಿನಾಂಕ',
    'forecast.timeBlock': 'ಸಮಯ ಬ್ಲಾಕ್',
    'forecast.topCells': 'ಟಾಪ್ ಸೆಲ್‌ಗಳು:',
    'forecast.scoring': 'ಸ್ಕೋರ್ ಮಾಡಲಾಗುತ್ತಿದೆ…',
    'forecast.run': 'ಮುನ್ಸೂಚನೆ ಚಲಾಯಿಸಿ',
    'forecast.empty':
      'ದಿನಾಂಕ ಮತ್ತು ಸಮಯ ಬ್ಲಾಕ್ ಆಯ್ಕೆಮಾಡಿ, ನಂತರ ನಕ್ಷೆಯಲ್ಲಿ ಅತ್ಯಂತ ಜನನಿಬಿಡ ಮುನ್ಸೂಚಿತ ಸೆಲ್‌ಗಳನ್ನು ನೋಡಲು ಮುನ್ಸೂಚನೆ ಚಲಾಯಿಸಿ.',
    'forecast.colNum': '#',
    'forecast.colPred': 'ಮುನ್ಸೂ. ಉಲ್ಲಂಘನೆ',
    'forecast.colCell': 'ಸೆಲ್',
    'forecast.colStation': 'ಪೊಲೀಸ್ ಠಾಣೆ',
    'forecast.popup.cell': 'ಸೆಲ್ {cell}',
    'forecast.popup.viol': '~{n} ಉಲ್ಲಂಘನೆ',

    'model.comparisonTitle': 'ಮಾಡೆಲ್ ಹೋಲಿಕೆ',
    'model.comparisonHint':
      'ಐತಿಹಾಸಿಕ-ಸರಾಸರಿ ಬೇಸ್‌ಲೈನ್ ವಿರುದ್ಧ ಐದು ಸ್ಪರ್ಧಿಗಳು, ತಾತ್ಕಾಲಿಕ ಹೋಲ್ಡ್-ಔಟ್‌ನಲ್ಲಿ ಮೌಲ್ಯಮಾಪನ. RMSE + ಟಾಪ್-K ಕ್ಯಾಪ್ಚರ್ ಆಧಾರದ ಮೇಲೆ ಆಯ್ಕೆ — ಜಾರಿಗೆ ಮುಖ್ಯವಾದ ಮೆಟ್ರಿಕ್.',
    'model.evidenceTitle': 'ಮುನ್ಸೂಚನೆಯನ್ನು ನಂಬಬಹುದು ಎಂಬುದಕ್ಕೆ ಸಾಕ್ಷಿ',
    'plot.model_capture_curve.png': 'ಜಾರಿ-ದಕ್ಷತೆ ರೇಖೆ',
    'plot.model_feature_importance.png': 'ಮಾಡೆಲ್ ಯಾವುದಕ್ಕೆ ಪ್ರಾಮುಖ್ಯ ನೀಡುತ್ತದೆ',
    'plot.model_comparison.png': 'ದೋಷ vs ದಕ್ಷತೆ',
    'plot.hotspot_map.png': 'ಸಾಂದ್ರತೆ ಮತ್ತು ಆದ್ಯತಾ ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳು',
    'plot.eda_temporal.png': 'ಉಲ್ಲಂಘನೆಗಳು ಯಾವಾಗ ಸಂಭವಿಸುತ್ತವೆ',
    'plot.eda_violation_types.png': 'ಉಲ್ಲಂಘನೆ ಮಿಶ್ರಣ',
    'plot.eda_vehicle_trend.png': 'ವಾಹನಗಳು ಮತ್ತು ಮಾಸಿಕ ಪ್ರವೃತ್ತಿ',
    'plot.eda_impact_dist.png': 'ಪ್ರಭಾವ ಸ್ಕೋರ್ ವಿತರಣೆ',

    'table.title': 'ಜಾರಿ ಆದ್ಯತಾ ಸೂಚ್ಯಂಕ — ಶ್ರೇಣೀಕೃತ ಸೆಲ್‌ಗಳು',
    'table.downloadCsv': 'CSV ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ',
    'table.hint':
      'ಪ್ರಾಥಮಿಕ ಗುರಿ ಘಟಕ. {count} ಸೆಲ್‌ಗಳನ್ನು EPI ಆಧಾರದ ಮೇಲೆ ಶ್ರೇಣೀಕರಿಸಲಾಗಿದೆ — ಮುಂದಿನ ಗಸ್ತು ಎಲ್ಲಿಗೆ ಹೋಗಬೇಕೆಂದು ನಿರ್ಧರಿಸುವ ಸುಗಮ, ಮುನ್ಸೂಚನೆ-ಚಾಲಿತ ಆದ್ಯತಾ ಸ್ಕೋರ್.',
    'table.col.rank': 'ಶ್ರೇಣಿ',
    'table.col.epi': 'EPI',
    'table.col.predDay': 'ಮುನ್ಸೂ./ದಿನ',
    'table.col.actualDay': 'ವಾಸ್ತವ/ದಿನ',
    'table.col.impactViol': 'ಪ್ರಭಾವ/ಉಲ್ಲಂಘನೆ',
    'table.col.events': 'ಘಟನೆಗಳು',
    'table.col.peakBlock': 'ಗರಿಷ್ಠ ಬ್ಲಾಕ್',
    'table.col.policeStation': 'ಪೊಲೀಸ್ ಠಾಣೆ',
    'table.col.junction': 'ಜಂಕ್ಷನ್',
    'table.zonesToggle': 'ದ್ವಿತೀಯ: DBSCAN ಸಾಂದ್ರತೆ ವಲಯಗಳು (ಬೀಟ್-ಮಟ್ಟದ ಗುಂಪು)',
  },
};

// Time-block labels arrive from the backend in English; map them per language.
// The English label stays the lookup key (and the value sent to the API).
export const BLOCKS = {
  hi: {
    'Late Night (00-04)': 'देर रात (00-04)',
    'Early Morning (04-08)': 'तड़के सुबह (04-08)',
    'Morning Peak (08-12)': 'सुबह पीक (08-12)',
    'Afternoon (12-16)': 'दोपहर (12-16)',
    'Evening Peak (16-20)': 'शाम पीक (16-20)',
    'Night (20-24)': 'रात (20-24)',
  },
  kn: {
    'Late Night (00-04)': 'ತಡರಾತ್ರಿ (00-04)',
    'Early Morning (04-08)': 'ಮುಂಜಾನೆ (04-08)',
    'Morning Peak (08-12)': 'ಬೆಳಗಿನ ಗರಿಷ್ಠ (08-12)',
    'Afternoon (12-16)': 'ಮಧ್ಯಾಹ್ನ (12-16)',
    'Evening Peak (16-20)': 'ಸಂಜೆ ಗರಿಷ್ಠ (16-20)',
    'Night (20-24)': 'ರಾತ್ರಿ (20-24)',
  },
};
