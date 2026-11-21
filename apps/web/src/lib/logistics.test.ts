import { describe, expect, it } from "vitest";

import { actionBody, shipmentActions, statusTone } from "./logistics";

const OPS = [
  "shipments.read",
  "shipments.write",
  "shipments.dispatch",
  "shipments.confirm_clearance",
  "delivery.confirm",
];
const DISPATCHER = ["shipments.read", "shipments.write", "shipments.dispatch"];

describe("shipmentActions", () => {
  it("mirrors the API state machine", () => {
    expect(shipmentActions("draft", OPS)).toEqual(["confirm", "cancel"]);
    expect(shipmentActions("in_transit", OPS)).toEqual(["border-arrival", "deliver", "delivery-failed", "delay"]);
    expect(shipmentActions("delivered", OPS)).toEqual([]);
    expect(shipmentActions("cancelled", OPS)).toEqual([]);
  });

  it("never offers border clearance to roles without that permission (hard rule 8)", () => {
    expect(shipmentActions("at_border", DISPATCHER)).not.toContain("border-clearance");
    expect(shipmentActions("at_border", OPS)).toContain("border-clearance");
  });

  it("hides delivery actions from users who cannot confirm deliveries", () => {
    expect(shipmentActions("in_transit", DISPATCHER)).toEqual(["border-arrival", "delay"]);
  });

  it("offers nothing to read-only users", () => {
    expect(shipmentActions("draft", ["shipments.read"])).toEqual([]);
  });
});

describe("actionBody", () => {
  it("maps form fields to the API payload", () => {
    expect(actionBody("cancel", { reason: "  Customer withdrew " })).toEqual({ reason: "Customer withdrew" });
    expect(actionBody("border-arrival", { border: "Galafi" })).toEqual({ border: "Galafi" });
    expect(actionBody("deliver", { recipient: "A. Recipient" })).toEqual({ recipient_name: "A. Recipient" });
    expect(actionBody("confirm", {})).toEqual({});
  });
});

describe("statusTone", () => {
  it("gives terminal and warning states distinct tones", () => {
    expect(statusTone("delivered")).toBe("success");
    expect(statusTone("cancelled")).toBe("danger");
    expect(statusTone("at_border")).toBe("warning");
    expect(statusTone("something-new")).toBe("neutral");
  });
});
