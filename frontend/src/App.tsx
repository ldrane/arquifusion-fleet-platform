import type { ReactNode } from "react";
import { createBrowserRouter, Link, Navigate, RouterProvider, useRouteError } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { type Capability, can } from "./auth/permissions";
import { AppShell } from "./components/layout/AppShell";
import { Empty, Icon } from "./components/ui";
import { FleetProvider } from "./state/FleetContext";
import { Assistant } from "./views/Assistant";
import { CommandCenter } from "./views/CommandCenter";
import { Dispatch } from "./views/Dispatch";
import { Efficiency } from "./views/Efficiency";
import { IncidentDetail } from "./views/IncidentDetail";
import { IncidentHistory } from "./views/IncidentHistory";
import { Inventory } from "./views/Inventory";
import { Login } from "./views/Login";
import { MachineDetail } from "./views/MachineDetail";
import { PredictiveHealth } from "./views/PredictiveHealth";

/** Protege una vista por capacidad (x-roles del OpenAPI). El backend vuelve a validar. */
function Guard({ caps, children }: { caps: Capability[]; children: ReactNode }) {
  const { role } = useAuth();
  if (caps.some((c) => can(role, c))) return <>{children}</>;
  return (
    <div className="panel">
      <Empty icon="lock" title="Tu rol no tiene acceso a esta vista">
        <Link to="/" className="text-primary hover:underline">Volver al Centro de Mando</Link>
      </Empty>
    </div>
  );
}

function RouteError() {
  const err = useRouteError() as { status?: number; message?: string } | undefined;
  return (
    <div className="panel">
      <Empty icon={err?.status === 404 ? "explore_off" : "error"} title={err?.status === 404 ? "Página no encontrada" : "Algo salió mal en esta vista"}>
        <p className="mb-2">{err?.message}</p>
        <Link to="/" className="inline-flex items-center gap-1 text-primary hover:underline">
          <Icon name="arrow_back" className="text-[14px]" />
          Volver al Centro de Mando
        </Link>
      </Empty>
    </div>
  );
}

/**
 * Rutas anidadas bajo AppShell: el layout, el FleetProvider (tiempo real) y las cachés NO se
 * desmontan al navegar, y cada vista guarda su estado de UI en useViewState.
 */
const router = createBrowserRouter([
  {
    element: (
      <FleetProvider>
        <AppShell />
      </FleetProvider>
    ),
    errorElement: <RouteError />,
    children: [
      { errorElement: <RouteError />, children: [
        { index: true, element: <Guard caps={["machines"]}><CommandCenter /></Guard> },
        { path: "salud", element: <Guard caps={["machines"]}><PredictiveHealth /></Guard> },
        { path: "salud/:id", element: <Guard caps={["machines"]}><MachineDetail /></Guard> },
        { path: "despacho", element: <Guard caps={["technicians", "myStatus"]}><Dispatch /></Guard> },
        { path: "inventario", element: <Guard caps={["inventory"]}><Inventory /></Guard> },
        { path: "eficiencia", element: <Guard caps={["fuel"]}><Efficiency /></Guard> },
        { path: "incidentes", element: <Guard caps={["incidents"]}><IncidentHistory /></Guard> },
        { path: "incidentes/:id", element: <Guard caps={["incidents"]}><IncidentDetail /></Guard> },
        { path: "asistente", element: <Guard caps={["assistant"]}><Assistant /></Guard> },
        { path: "login", element: <Navigate to="/" replace /> },
        { path: "*", element: <RouteError /> },
      ] },
    ],
  },
]);

export function App() {
  const { me } = useAuth();
  if (!me) return <Login />;
  return <RouterProvider router={router} />;
}
