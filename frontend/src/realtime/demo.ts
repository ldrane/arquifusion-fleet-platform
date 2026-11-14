import type { Me } from "@/api/types";
import { can } from "@/auth/permissions";
import { DEMO_USERS } from "@/demo/data";
import type { DemoWorld, Topic } from "@/demo/world";
import { myTechnicianId } from "@/lib/ids";
import type { FleetUpdate, RealtimeSource } from "./types";

/** Tiempo real del modo demo. Aplica la misma visibilidad que las Security Rules (rol + zona). */
export class DemoRealtime implements RealtimeSource {
  readonly kind = "demo" as const;
  readonly canChat = true;
  private me: Me | null = null;

  constructor(private readonly world: DemoWorld) {}

  private snapshot(me: Me, topics: Set<Topic>): FleetUpdate {
    const zoneOk = (z?: string | null) => !me.zone || z === me.zone;
    const u: FleetUpdate = {};
    if (topics.has("machines")) {
      u.machines = [...this.world.machines.values()].filter((m) => zoneOk(m.home.zone)).map((m) => this.world.publicMachine(m));
    }
    if (topics.has("incidents")) {
      u.incidents = [...this.world.incidents.values()].filter((i) => zoneOk(i.zone)).map((i) => this.world.publicIncident(i));
    }
    if (topics.has("technicians")) {
      const ownId = myTechnicianId(me);
      u.technicians = [...this.world.techs.values()]
        .filter((t) => (can(me.role, "technicians") && zoneOk(t.zone)) || t.technician_id === ownId)
        .map((t) => this.world.publicTech(t));
    }
    return u;
  }

  start(me: Me, onUpdate: (u: FleetUpdate) => void) {
    this.me = me;
    this.world.start();
    onUpdate(this.snapshot(me, new Set<Topic>(["machines", "incidents", "technicians"])));
    const unsub = this.world.subscribe((topics) => {
      const u = this.snapshot(me, topics);
      if (u.machines || u.incidents || u.technicians) onUpdate(u);
    });
    return () => {
      unsub();
      this.me = null;
    };
  }

  subscribeMessages(incidentId: string, onMessages: (m: import("@/api/types").ChatMessage[]) => void) {
    const parent = this.world.incidents.get(incidentId)?.parent_incident_id ?? incidentId;
    const emit = () => onMessages([...(this.world.messages.get(parent) ?? [])]);
    emit();
    return this.world.subscribe((topics) => topics.has("messages") && emit());
  }

  async sendMessage(incidentId: string, text: string, quickAction?: string | null) {
    const me = this.me;
    if (!me) throw new Error("Sin sesión");
    if (!can(me.role, "chatWrite")) throw new Error("Tu rol solo puede leer el chat");
    const parent = this.world.incidents.get(incidentId)?.parent_incident_id ?? incidentId;
    const name = DEMO_USERS.find((u) => u.user_id === me.user_id)?.name ?? me.user_id;
    this.world.chat(parent, { user_id: me.user_id, role: me.role, name, technician_id: myTechnicianId(me) }, text, quickAction);
  }

  subscribeNotifications(onNotifications: (n: import("@/demo/world").Notification[]) => void) {
    const emit = () => onNotifications([...this.world.notifications]);
    emit();
    return this.world.subscribe((topics) => topics.has("notifications") && emit());
  }
}
