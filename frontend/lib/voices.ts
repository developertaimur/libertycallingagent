/** SignalWire-catalog Cartesia voices (work on SWML live calls). */

export type VoiceGender = "women" | "men";

export type CatalogVoice = {
  id: string;
  name: string;
  gender: VoiceGender;
  blurb: string;
};

export const CATALOG_VOICES: CatalogVoice[] = [
  // Women
  {
    id: "694f9389-aac1-45b6-b726-9d9369183238",
    name: "Sarah",
    gender: "women",
    blurb: "Warm and easy — sounds like a real conversation",
  },
  {
    id: "156fb8d2-335b-4950-9cb3-a2d33befec77",
    name: "Emily",
    gender: "women",
    blurb: "Friendly, clear, and approachable",
  },
  {
    id: "00a77add-48d5-4ef6-8157-71e5437b282d",
    name: "Olivia",
    gender: "women",
    blurb: "Calm and steady — never rushed",
  },
  {
    id: "b7d50908-b17c-442d-ad8d-810c63997ed9",
    name: "Jessica",
    gender: "women",
    blurb: "Bright and casual, like chatting with a friend",
  },
  {
    id: "15a9cd88-84b0-4a8b-95f2-5d583b54c72e",
    name: "Hannah",
    gender: "women",
    blurb: "Clear and natural storytelling tone",
  },
  {
    id: "bf991597-6c13-47e4-8411-91ec2de5c466",
    name: "Rachel",
    gender: "women",
    blurb: "Confident without sounding stiff",
  },
  {
    id: "71a7ad14-091c-4e8e-a314-022ece01c121",
    name: "Charlotte",
    gender: "women",
    blurb: "Polished UK tone, still conversational",
  },
  {
    id: "5345cf08-6f37-424d-a5d9-8ae1101b9377",
    name: "Maria",
    gender: "women",
    blurb: "Warm and welcoming",
  },
  // Men
  {
    id: "a0e99841-438c-4a64-b679-ae501e7d6091",
    name: "James",
    gender: "men",
    blurb: "Friendly and down-to-earth",
  },
  {
    id: "a167e0f3-df7e-4d52-a9c3-f949145efdab",
    name: "Michael",
    gender: "men",
    blurb: "Clear and professional, still human",
  },
  {
    id: "f146dcec-e481-45be-8ad2-96e1e40e7f32",
    name: "David",
    gender: "men",
    blurb: "Steady, natural pacing",
  },
  {
    id: "34575e71-908f-4ab6-ab54-b08c95d6597d",
    name: "Anthony",
    gender: "men",
    blurb: "Direct and conversational",
  },
  {
    id: "d46abd1d-2d02-43e8-819f-51fb652c1c61",
    name: "Daniel",
    gender: "men",
    blurb: "Strong presence without sounding scripted",
  },
  {
    id: "79f8b5fb-2cc8-479a-80df-29f7a7cf1a3e",
    name: "William",
    gender: "men",
    blurb: "Thoughtful and easy to follow",
  },
  {
    id: "b043dea0-a007-4bbe-a708-769dc0d0c569",
    name: "Thomas",
    gender: "men",
    blurb: "Calm and experienced",
  },
  {
    id: "69267136-1bdc-412f-ad78-0caad210fb40",
    name: "Andrew",
    gender: "men",
    blurb: "Warm and easy to listen to",
  },
];

export function voicesByGender(gender: VoiceGender): CatalogVoice[] {
  return CATALOG_VOICES.filter((v) => v.gender === gender);
}

export function findCatalogVoice(id: string): CatalogVoice | undefined {
  const bare = (id || "").replace(/^cartesia\./, "").split(":")[0];
  return CATALOG_VOICES.find((v) => v.id === bare || v.id === id);
}
