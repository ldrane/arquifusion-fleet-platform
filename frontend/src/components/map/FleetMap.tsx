import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { Circle, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { Incident, Machine, Technician } from "@/api/types";
import { SEED } from "@/demo/data";
import { SEVERITY_LABEL, STATUS_LABEL, TYPE_LABEL } from "@/lib/format";
import { useViewState } from "@/state/viewState";

export type MapFilter = "all" | "critical" | "techs";

const SEV_COLOR: Record<string, string> = {
  critical: "#ffb4ab",
  high: "#ff8a7a",
  medium: "#ffb95f",
  low: "#adc6ff",
  info: "#4edea3",
};

function machineColor(m: Machine) {
  if (m.status === "silent") return "#64748b";
  if (m.severity !== "info") return SEV_COLOR[m.severity]!;
  return m.status === "operational" ? "#4edea3" : "#ffb95f";
}

const iconCache = new Map<string, L.DivIcon>();

function machineIcon(m: Machine, selected: boolean) {
  const color = machineColor(m);
  const alert = m.severity === "critical" || m.severity === "high";
  const key = `${color}|${alert}|${selected}|${m.status}`;
  const cached = iconCache.get(key);
  if (cached) return cached;
  const size = alert ? 22 : 12;
  const html = alert
    ? `<div style="position:relative;width:${size}px;height:${size}px">
         <span class="af-ping" style="position:absolute;inset:0;border-radius:9999px;background:${color};opacity:.35"></span>
         <span style="position:absolute;inset:0;border-radius:9999px;background:${color};border:2px solid #0b0c10;box-shadow:0 0 12px ${color};display:flex;align-items:center;justify-content:center;color:#690005;font:700 12px 'Material Symbols Outlined'">priority_high</span>
         ${selected ? `<span style="position:absolute;inset:-6px;border:1.5px solid #adc6ff;border-radius:9999px"></span>` : ""}
       </div>`
    : `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${color};border:2px solid #0b0c10;box-shadow:0 0 6px ${color}${m.status === "silent" ? ";opacity:.7" : ""};${selected ? "outline:2px solid #adc6ff;outline-offset:2px" : ""}"></div>`;
  const icon = L.divIcon({ className: "af-marker", html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
  iconCache.set(key, icon);
  return icon;
}

const techIcon = (busy: boolean) =>
  L.divIcon({
    className: "af-marker",
    html: `<div style="width:26px;height:26px;border-radius:8px;background:${busy ? "#ffb95f" : "#adc6ff"};color:#002e6a;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.6);border:2px solid #0b0c10;font:400 15px 'Material Symbols Outlined'">engineering</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });

const warehouseIcon = L.divIcon({
  className: "af-marker",
  html: `<div style="width:22px;height:22px;border-radius:6px;background:#16181e;color:#a3a8b4;display:flex;align-items:center;justify-content:center;border:1px solid #2e323b;font:400 14px 'Material Symbols Outlined'">warehouse</div>`,
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

/** Mapas base sin API key (Esri). "dark" para la consola; "satellite" para ver el tajo real. */
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";
const BASEMAPS = {
  dark: {
    url: `${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
    maxNativeZoom: 16,
    maxZoom: 19,
  },
  satellite: {
    url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`,
    attribution: "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics",
    maxNativeZoom: 18,
    maxZoom: 19,
  },
} as const;
export type Basemap = keyof typeof BASEMAPS;

const zoneLabel = (zone: string, hot: boolean) =>
  L.divIcon({
    className: "af-marker",
    html: `<div style="transform:translate(-50%,-50%);display:inline-block;white-space:nowrap;padding:2px 8px;border-radius:9999px;background:rgba(10,14,24,.85);border:1px solid ${hot ? "#ffb4ab" : "#2e323b"};color:${hot ? "#ffb4ab" : "#a3a8b4"};font:600 10px 'JetBrains Mono',monospace;letter-spacing:.08em;text-transform:uppercase">${zone}</div>`,
    iconSize: [0, 0],
  });

function MapControls({ layer, onLayer }: { layer: Basemap; onLayer: (l: Basemap) => void }) {
  const map = useMap();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) {
      L.DomEvent.disableClickPropagation(ref.current);
      L.DomEvent.disableScrollPropagation(ref.current);
    }
  }, []);
  const btn = "flex h-7 w-7 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container";
  return (
    <div className="leaflet-bottom leaflet-right" style={{ pointerEvents: "auto" }}>
      <div ref={ref} className="leaflet-control mb-7 mr-3 flex items-center gap-1 rounded-full border border-hairline bg-surface-container-lowest/90 p-1 backdrop-blur-md">
        <button type="button" className={btn} title="Acercar" aria-label="Acercar" onClick={() => map.zoomIn()}>
          <span className="icon text-[18px]">add</span>
        </button>
        <button type="button" className={btn} title="Alejar" aria-label="Alejar" onClick={() => map.zoomOut()}>
          <span className="icon text-[18px]">remove</span>
        </button>
        <button
          type="button"
          className={`${btn} ${layer === "satellite" ? "text-primary" : ""}`}
          title={layer === "dark" ? "Ver satélite" : "Ver mapa oscuro"}
          aria-label="Cambiar capa del mapa"
          aria-pressed={layer === "satellite"}
          onClick={() => onLayer(layer === "dark" ? "satellite" : "dark")}
        >
          <span className="icon text-[16px]">{layer === "dark" ? "satellite_alt" : "layers"}</span>
        </button>
      </div>
    </div>
  );
}

/** Centro y radio de cada zona a partir de las posiciones base de los seeds. */
const ZONE_GEOMETRY = (() => {
  const by = new Map<string, { lat: number; lon: number }[]>();
  for (const m of SEED.machines) by.set(m.zone, [...(by.get(m.zone) ?? []), m.home_location]);
  return [...by.entries()].map(([zone, pts]) => {
    const lat = pts.reduce((a, p) => a + p.lat, 0) / pts.length;
    const lon = pts.reduce((a, p) => a + p.lon, 0) / pts.length;
    const r = Math.max(...pts.map((p) => Math.hypot(p.lat - lat, p.lon - lon))) * 111_000 + 250;
    return { zone, center: [lat, lon] as [number, number], radius: r };
  });
})();

function FitOnce({ points, zone }: { points: [number, number][]; zone: string }) {
  const map = useMap();
  const done = useRef<string | null>(null);
  useEffect(() => {
    if (!points.length || done.current === zone) return;
    done.current = zone;
    map.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 15 });
  }, [map, points, zone]);
  return null;
}

export function FleetMap({
  machines,
  technicians,
  incidents,
  filter = "all",
  selectedId,
  onSelect,
  zone = "",
  className,
}: {
  machines: Machine[];
  technicians: Technician[];
  incidents: Incident[];
  filter?: MapFilter;
  selectedId?: string | null;
  onSelect?: (machineId: string) => void;
  zone?: string;
  className?: string;
}) {
  const shown = useMemo(
    () => (filter === "critical" ? machines.filter((m) => m.severity === "critical" || m.severity === "high" || m.status === "silent") : filter === "techs" ? [] : machines),
    [machines, filter],
  );
  const machineById = useMemo(() => new Map(machines.map((m) => [m.machine_id, m])), [machines]);
  const hotZones = new Set(incidents.filter((i) => i.status !== "closed" && (i.severity === "critical" || i.severity === "high")).map((i) => i.zone));
  const routes = incidents
    .filter((i) => i.status === "in_progress" || i.status === "assigned")
    .flatMap((i) => {
      const t = technicians.find((x) => x.technician_id === i.assigned_technician_id);
      const m = machineById.get(i.machine_ids[0] ?? "");
      return t && m ? [{ id: i.incident_id, from: [t.location.lat, t.location.lon] as [number, number], to: [m.location.lat, m.location.lon] as [number, number], active: i.status === "in_progress" }] : [];
    });
  const [layer, setLayer] = useViewState<Basemap>("map.layer", "satellite");
  const fitPoints = useMemo(() => machines.map((m) => [m.location.lat, m.location.lon] as [number, number]), [machines.length, zone]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={className ?? "h-[540px] w-full"}>
      <MapContainer center={[-11.95, -76.4]} zoom={13} className="h-full w-full" zoomControl={false} attributionControl preferCanvas={false}>
        <TileLayer key={layer} {...BASEMAPS[layer]} />
        <MapControls layer={layer} onLayer={setLayer} />
        <FitOnce points={fitPoints} zone={zone} />
        {ZONE_GEOMETRY.filter((z) => !zone || z.zone === zone).map((z) => (
          <Circle
            key={z.zone}
            center={z.center}
            radius={z.radius}
            pathOptions={{
              color: hotZones.has(z.zone) ? "#ffb4ab" : "#6f7582",
              weight: 1.5,
              dashArray: "4 4",
              fillColor: hotZones.has(z.zone) ? "#93000a" : "#16181e",
              fillOpacity: hotZones.has(z.zone) ? 0.14 : 0.1,
            }}
          />
        ))}
        {ZONE_GEOMETRY.filter((z) => !zone || z.zone === zone).map((z) => (
          <Marker key={`label-${z.zone}`} position={[z.center[0] + z.radius / 111_000, z.center[1]]} icon={zoneLabel(z.zone, hotZones.has(z.zone))} interactive={false} />
        ))}
        {SEED.warehouses
          .filter((w) => !zone || w.zone === zone)
          .map((w) => (
            <Marker key={w.warehouse_id} position={[w.location.lat, w.location.lon]} icon={warehouseIcon}>
              <Tooltip className="af-tooltip" direction="top" offset={[0, -10]}>
                <b className="font-mono text-xs">{w.warehouse_id}</b> · {w.name}
              </Tooltip>
            </Marker>
          ))}
        {routes.map((r) => (
          <Polyline key={r.id} positions={[r.from, r.to]} pathOptions={{ color: r.active ? "#adc6ff" : "#ffb95f", weight: 2, dashArray: "6 4", opacity: 0.8 }} />
        ))}
        {shown.map((m) => (
          <Marker
            key={m.machine_id}
            position={[m.location.lat, m.location.lon]}
            icon={machineIcon(m, m.machine_id === selectedId)}
            zIndexOffset={m.severity === "critical" ? 1000 : m.severity === "high" ? 800 : 0}
            eventHandlers={{ click: () => onSelect?.(m.machine_id) }}
            keyboard
            title={m.machine_id}
          >
            <Tooltip className="af-tooltip" direction="right" offset={[10, 0]}>
              <div className="min-w-[180px]">
                <div className="flex items-center justify-between gap-3">
                  <b className="font-mono text-xs" style={{ color: machineColor(m) }}>
                    {m.machine_id}
                  </b>
                  <span className="font-mono text-[10px] text-outline">{m.model}</span>
                </div>
                <div className="text-[11px] text-on-surface-variant">
                  {TYPE_LABEL[m.type]} · {STATUS_LABEL[m.status]}
                </div>
                <div className="text-[11px] text-on-surface-variant">
                  Health {m.health_score}/100{m.severity !== "info" ? ` · ${SEVERITY_LABEL[m.severity]}` : ""}
                </div>
              </div>
            </Tooltip>
          </Marker>
        ))}
        {(filter !== "critical" ? technicians : []).map((t) => (
          <Marker key={t.technician_id} position={[t.location.lat, t.location.lon]} icon={techIcon(!t.available)} zIndexOffset={1200}>
            <Tooltip className="af-tooltip" direction="right" offset={[12, 0]}>
              <b className="text-xs text-primary">{t.name}</b>
              <div className="text-[11px] text-on-surface-variant">
                {t.technician_id} · {t.available ? "Disponible" : "Ocupado"} · carga {t.current_load}
              </div>
            </Tooltip>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}
