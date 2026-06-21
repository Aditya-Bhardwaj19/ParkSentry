import { useEffect, useMemo, useState } from 'react';
import MapView from './MapView.jsx';
import { Icon } from './icons.jsx';
import { getBlocks, getStations, getHotspots } from '../api.js';
import { useT } from '../i18n/index.jsx';

export default function PriorityMap() {
  const { t, tBlock } = useT();
  const [blocks, setBlocks] = useState({}); // {idx: label}
  const [stations, setStations] = useState([]);
  const [selBlocks, setSelBlocks] = useState(null); // null = all
  const [selStations, setSelStations] = useState([]);
  const [stationQuery, setStationQuery] = useState('');
  const [topN, setTopN] = useState(100);
  const [cells, setCells] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    getBlocks()
      .then((b) => {
        setBlocks(b);
        setSelBlocks(Object.values(b));
      })
      .catch((e) => setErr(e.message));
    getStations().then(setStations).catch(() => {});
  }, []);

  useEffect(() => {
    if (selBlocks === null) return;
    const allBlocks = Object.values(blocks);
    const params = { top: topN };
    if (allBlocks.length && selBlocks.length < allBlocks.length) {
      params.blocks = selBlocks.join(',');
    }
    if (selStations.length) params.stations = selStations.join(',');
    getHotspots(params)
      .then((d) => setCells(d.cells))
      .catch((e) => setErr(e.message));
  }, [topN, selBlocks, selStations, blocks]);

  const points = useMemo(
    () =>
      cells.map((c) => ({
        lat: c.lat,
        lon: c.lon,
        epi: c.EPI,
        popup:
          `<b>${t('map.popup.rank', { rank: c.rank })}</b> &nbsp;EPI ${c.EPI}<br/>` +
          `${c.dom_police_station} — ${c.dom_junction}<br/>` +
          `${t('map.popup.perDay', { n: (c.pred_daily_viol || 0).toFixed(1) })} · ${tBlock(c.peak_block_label)}`,
      })),
    [cells, t, tBlock]
  );

  const visibleStations = useMemo(
    () =>
      stations.filter((s) =>
        s.toLowerCase().includes(stationQuery.trim().toLowerCase())
      ),
    [stations, stationQuery]
  );

  const toggleBlock = (label) => {
    setSelBlocks((prev) => {
      const cur = prev || Object.values(blocks);
      return cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label];
    });
  };

  return (
    <div>
      <p className="hint">{t('map.hint')}</p>
      {err && <div className="error-banner">{err}</div>}
      <div className="map-layout">
        <aside className="panel controls">
          <div className="control">
            <div className="control-title">
              {t('map.topN')} <span className="val">{topN}</span>
            </div>
            <input
              type="range"
              min="10"
              max="500"
              step="10"
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
            />
          </div>

          <div className="control">
            <div className="control-title">{t('map.peakBlock')}</div>
            {Object.values(blocks).map((label) => (
              <label key={label} className="checkbox">
                <input
                  type="checkbox"
                  checked={(selBlocks || []).includes(label)}
                  onChange={() => toggleBlock(label)}
                />
                {tBlock(label)}
              </label>
            ))}
          </div>

          <div className="control">
            <div className="control-title">
              {t('map.policeStation')}
              {selStations.length > 0 && (
                <span className="val">{selStations.length}</span>
              )}
            </div>
            <input
              className="station-search"
              type="text"
              placeholder={t('map.filterStations')}
              value={stationQuery}
              onChange={(e) => setStationQuery(e.target.value)}
            />
            <select
              multiple
              size="7"
              value={selStations}
              onChange={(e) =>
                setSelStations(Array.from(e.target.selectedOptions, (o) => o.value))
              }
            >
              {visibleStations.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <div className="control-meta">
              <span>{t('map.stations', { count: visibleStations.length })}</span>
              {selStations.length > 0 && (
                <button className="link-btn" onClick={() => setSelStations([])}>
                  {t('map.clear')}
                </button>
              )}
            </div>
          </div>

          <div className="control-meta" style={{ marginTop: 4 }}>
            <span>
              <Icon name="pin" size={12} /> {t('map.cellsShown', { count: cells.length })}
            </span>
          </div>
        </aside>

        <div className="map-wrap">
          <MapView points={points} height={560} />
        </div>
      </div>
    </div>
  );
}
