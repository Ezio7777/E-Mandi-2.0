export const SAMPLE_CROPS = [
  { id: "tomato", name: "Tomato", src: "/demo-crops/tomato.svg" },
  { id: "potato", name: "Potato", src: "/demo-crops/potato.svg" },
  { id: "onion", name: "Onion", src: "/demo-crops/onion.svg" },
  { id: "cabbage", name: "Cabbage", src: "/demo-crops/cabbage.svg" },
] as const;
export type SampleCrop = (typeof SAMPLE_CROPS)[number];
