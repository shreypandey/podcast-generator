// Realistic demo episode used by the mock backend — the real mRNA run (20260712-171445):
// authentic cast, English/Hindi/Tamil deliveries, honest unverified flags, real sources +
// per-citation source quotes (the P1 enhancement the review asks the backend to expose).

import type { Cast, Citation, CitationDetail, SourceItem, TranscriptTurn } from "./types";

export const MRNA_CAST: Cast = {
  host: {
    name: "Alex",
    background: "Science journalist with a knack for breaking down complex topics.",
    gender: "male",
    voice: "aditya",
  },
  expert: {
    name: "Dr. Lena Petrova",
    background: "Immunologist developing next-generation vaccines and immunotherapies.",
    gender: "female",
    voice: "priya",
  },
};

export const MRNA_CITATIONS: CitationDetail[] = [
  {
    number: 1,
    fact_id: "F3",
    source_id: "S1",
    source_title: "COVID-19 Vaccine Basics | CDC",
    source_url: "https://www.cdc.gov/covid/vaccines/how-they-work.html",
    quote:
      "mRNA vaccines teach our cells how to make a harmless piece of the spike protein, which triggers an immune response inside our bodies.",
  },
  {
    number: 2,
    fact_id: "F7",
    source_id: "S2",
    source_title:
      "mRNA vaccines in cancer immunotherapy: current progress and perspectives",
    source_url: "https://journal.hep.com.cn/fmd/EN/10.1007/s11684-026-1210-6",
    quote:
      "The synthetic mRNA is engineered with a 5' cap and poly-A tail that protect it from degradation, while optimized UTRs regulate translation efficiency and reduce innate immune recognition.",
  },
];

// Compact source-link list for transcript.sources[] (derived from the rich citations).
export const MRNA_TRANSCRIPT_SOURCES: Citation[] = MRNA_CITATIONS.map((c) => ({
  number: c.number,
  id: c.source_id,
  title: c.source_title,
  url: c.source_url,
}));

export const MRNA_SOURCES: SourceItem[] = [
  {
    id: "S1",
    title: "COVID-19 Vaccine Basics | COVID-19 | CDC",
    url: "https://www.cdc.gov/covid/vaccines/how-they-work.html",
    origin: "exa",
    query_ids: ["Q1"],
    query_intents: ["core_explainer", "primary_official"],
    search_rank: 1,
    quality_score: 0.94,
    fact_ids: ["F1", "F3", "F9"],
    snippet:
      "mRNA vaccines use mRNA created in a laboratory to teach our cells how to make a protein that triggers an immune response.",
  },
  {
    id: "S2",
    title:
      "mRNA vaccines in cancer immunotherapy: current progress and perspectives in solid tumors and hematologic malignancies",
    url: "https://journal.hep.com.cn/fmd/EN/10.1007/s11684-026-1210-6",
    origin: "exa",
    query_ids: ["Q2", "Q3"],
    query_intents: ["recent_current", "caveat_critique"],
    search_rank: 2,
    quality_score: 0.81,
    fact_ids: ["F5", "F7"],
    snippet:
      "Structural elements including the 5' cap, UTRs and poly-A tail are engineered to improve stability and translation.",
  },
  {
    id: "S3",
    title: "Understanding mRNA and how it is used in vaccines — NIH",
    url: "https://www.nih.gov/mrna-vaccines-explained",
    origin: "exa",
    query_ids: ["Q1"],
    query_intents: ["core_explainer"],
    search_rank: 3,
    quality_score: 0.88,
    fact_ids: ["F2"],
    snippet:
      "Once the protein piece is made, the cell breaks down the mRNA and removes it.",
  },
];

interface MRNATurn {
  speaker: "host" | "expert";
  move: string;
  verified: boolean;
  cites: number[];
  en: string;
  hi: string;
  ta: string;
}

// Deliveries lifted verbatim from transcript_{en,hi,ta}-IN.md of the real run.
const T: MRNATurn[] = [
  {
    speaker: "host", move: "intro", verified: true, cites: [],
    en: "Welcome, everyone! Today we're talking about how mRNA vaccines work, and it all starts with a fascinating question... you know, have you ever wondered how a vaccine can teach your body to fight a virus without actually using the virus itself? I'm so excited to be joined by the brilliant immunologist Dr. Lena Petrova to help us understand it all.",
    hi: "स्वागत है आप सभी का! आज का टॉपिक है कि mRNA वैक्सिन्स कैसे काम करती हैं, और इसकी शुरुआत एक बहुत ही दिलचस्प सवाल से होती है: मतलब, क्या आपने कभी सोचा है कि एक वैक्सिन, बिना असली वायरस के, आपके शरीर को वायरस से लड़ना सिखा सकती है? मुझे बहुत खुशी है कि शानदार इम्यूनोलॉजिस्ट डॉक्टर लीना पेट्रोवा मेरे साथ जुड़ रही हैं।",
    ta: "வணக்கம் எல்லாருக்கும்! இன்னைக்கு நம்ம டாபிக்... எம் ஆர் என் ஏ வேக்சின்ஸ் எப்படி வொர்க் ஆகுதுங்கறது தான். வைரஸ யூஸ் பண்ணாம எப்படி வேக்சின் நம்ம பாடிக்கு வைரஸ ஃபைட் பண்ண கத்துக்கொடுக்கும்? இதெல்லாம் புரிஞ்சுக்க பிரில்லியண்ட் இம்யூனாலஜிஸ்ட் டாக்டர் லீனா பெட்ரோவா கூட ஜாயின் பண்றதுல எனக்கு ரொம்ப எக்ஸைட்மெண்ட்.",
  },
  {
    speaker: "expert", move: "intro", verified: true, cites: [],
    en: "Hi Alex, everyone... it's so great to be here discussing mRNA vaccines—I mean, what a revolutionary approach to training our immune system, really changing the landscape of medicine. And I'm excited to walk you through how these remarkable vaccines work at the cellular level.",
    hi: "एलेक्स और सब! यहाँ आकर mRNA vaccines पर बात करके बहुत अच्छा लग रहा है... तो, ये हमारे इम्यून सिस्टम को ट्रेन करने का एक क्रांतिकारी तरीका है, जो मॉडर्न मेडिसिन के लैंडस्केप को बदल रहा है।",
    ta: "ஹாய் அலெக்ஸே அண்ட் எவ்ரிஒன்! எம் ஆர் என் ஏ வேக்சின் பத்தி இங்க டிஸ்கஸ் பண்றது ரொம்ப சந்தோஷமா இருக்கு. நம்ம இம்யூன் சிஸ்டம டிரெய்ன் பண்றதுல இது ஒரு ரெவல்யூஷனரி அப்ரோச்.",
  },
  {
    speaker: "host", move: "ask", verified: true, cites: [],
    en: "That's a great way to put it. So, the mRNA is the blueprint, but... how does it actually get inside our cells and get them to follow it and make that viral protein?",
    hi: "वाह, यह तो बहुत बढ़िया है। तो, एम आर एन ए ब्लूप्रिंट है, पर यह हमारे सेल्स के अंदर असल में कैसे पहुँचता है... और उन्हें उस वायरल प्रोटीन को बनाने के लिए कहता है?",
    ta: "அத சொன்ன விதம் ரொம்ப சூப்பர். சரி, அப்போ எம் ஆர் என் ஏங்கறது ப்ளூப்ரிண்ட் மாதிரி தான். ஆனா, அது எப்படி நம்ம செல்ஸ்க்குள்ள போய்... அந்த வைரல் புரோட்டீன ப்ரொடியூஸ் பண்ண வைக்கும்?",
  },
  {
    speaker: "expert", move: "explain", verified: true, cites: [1],
    en: "So, that lab-created mRNA blueprint, our cells actually take it up, and then they follow the instructions to make that harmless little piece of the spike protein.",
    hi: "लैबोरेटरी क्रिएटेड एम आर एन ए ब्लूप्रिंट हमारे सेल्स में यूज़ होता है, जो फिर उसके इंस्ट्रक्शन्स फॉलो करके स्पाइक प्रोटीन का हार्मलेस पीस प्रोड्यूस करते हैं।",
    ta: "ஆ, lab-created mRNA blueprint நம்ம செல்களுக்குள்ள போய்டும். அது அப்புறம் அதோட இன்ஸ்ட்ரக்ஷன்ஸ ஃபாலோ பண்ணி, ஸ்பைக் புரோட்டீனோட அந்த பாதிப்பில்லாத பீஸ ப்ரொடியூஸ் பண்ணும்.",
  },
  {
    speaker: "host", move: "ask", verified: true, cites: [],
    en: "Right, that's the part that really gets me. How does something as fragile as an mRNA molecule even survive long enough to get inside a cell... without the body's defenses just destroying it?",
    hi: "वो पार्ट मुझे रिमार्केबल लग रहा है। matlab, एक एम आर एन ए मॉलिक्यूल... जो इतना फ्रेजाइल है... बॉडी के डिफेंसेस से डिस्ट्रॉय हुए बिना... सेल के अंदर जाने के लिए... वो कैसे सर्वाइव करता है?",
    ta: "அதுதான் எனக்கு ரொம்ப ரிமார்க்கபிளா தெரியுது. ஒரு எம் ஆர் என் ஏ மாலிக்யூல்ங்கற ஃப்ராஜைலான மாலிக்யூல்... பாடிஓட டிஃபென்சஸ்னால டிஸ்ட்ராய் ஆகாம, செல்லுக்குள்ள போறதுக்கு எப்படி சர்வைவ் பண்ணும்?",
  },
  {
    speaker: "expert", move: "explain", verified: false, cites: [2],
    en: "Right, so the synthetic mRNA is engineered with a five prime cap and a poly-A tail... which protect it from degradation enzymes. And then, the UTRs—they help regulate translation efficiency, but also reduce recognition by our innate immune sensors.",
    hi: "सिंथेटिक एम आर एन ए में, तो, एक फाइव प्राइम कैप और एक पॉली (A) टेल ऐड की जाती है... जो इसे डिग्रेडेशन एंजाइम्स से प्रोटेक्ट करती है... और 5' UTRs ट्रांसलेशन एफिशिएंसी रेगुलेट करने में मदद करते हैं।",
    ta: "செயற்கை mRNA-க்கு, ஐந்து அடி கேப் மற்றும் பாலி A வால் இன்ஜினியர் பண்ணிருக்காங்க... இது சிதைவு என்சைம்களிலிருந்து பாதுகாப்பா இருக்கும். UTR-கள் மொழிபெயர்ப்புத் திறனை ஒழுங்குபடுத்தும்.",
  },
  {
    speaker: "host", move: "challenge", verified: true, cites: [],
    en: "Okay, so you've built this molecular stealth... to get past the initial defenses. But when the rest of the immune system finally does detect it, what are the most significant potential side effects we're talking about... even if they're rare?",
    hi: "अरे तो, आपने इनिशियल डिफेन्सेस को क्रॉस करने के लिए ये मॉलिक्यूलर स्टेल्थ बनाया है... लेकिन जब बाकी इम्यून सिस्टम फाइनली डिटेक्ट करता है, तो सबसे सिग्निफिकेंट पोटेंशियल साइड इफेक्ट्स क्या होते हैं?",
    ta: "அப்போ, நீங்க இந்த molecular stealth-அ build பண்ணிருக்கீங்க. ஆனா, immune system இத கண்டுபிடிச்சா—அதுவும் அரிதா இருந்தாலும்—பெரிய potential side effects என்னென்ன பாக்கலாம்?",
  },
  {
    speaker: "expert", move: "explain", verified: false, cites: [1],
    en: "So, the most significant potential side effects are the serious adverse events, but... the most important takeaway from the data is that they are reported to be rare.",
    hi: "सबसे इम्पॉर्टेन्ट पोटेंशियल साइड इफेक्ट्स तो सीरियस एडवर्स इवेंट्स ही हैं... लेकिन डेटा से इम्पॉर्टेन्ट बात यह है कि ये रेयर ही बताए गए हैं।",
    ta: "மிக முக்கியமான சாத்தியமான பக்கவிளைவுகள்... அப்படின்னா, அவை கடுமையான பக்கவிளைவுகள் தான். ஆனா டேட்டால இருந்து முக்கியமான விஷயம் என்னன்னா... அவை ரொம்ப அபூர்வம்.",
  },
  {
    speaker: "expert", move: "outro", verified: true, cites: [],
    en: "Alex, so to wrap up, the main takeaway is that mRNA vaccines are a clever, temporary training program for your immune system. But the real excitement—what's still so uncertain—is in refining that blueprint to tackle other diseases, like cancer.",
    hi: "एलेक्स, तो चलिए समराइज़ करते हैं, मुख्य बात ये है कि एम आर एन ए वैक्सीन आपके इम्यून सिस्टम के लिए एक चतुर, अस्थायी ट्रेनिंग प्रोग्राम है। असली एक्साइटमेंट है उस ब्लूप्रिंट को रिफाइन करना... ताकि कैंसर जैसी बीमारियों को टैकल किया जा सके।",
    ta: "அலெக்ஸ், சொல்லப்போனா, எம் ஆர் என் ஏ வேக்சின்ங்கறது உங்க இம்யூன் சிஸ்டமுக்கு ஒரு புத்திசாலித்தனமான, தற்காலிகமான பயிற்சி புரோகிராம் தான்... ஆனா, உண்மையான உற்சாகம் என்னன்னா, அந்த ப்ளூப்ரிண்ட்டை கேன்சர் போன்ற நோய்களை எதிர்கொள்ள மாற்றுவது தான்.",
  },
  {
    speaker: "host", move: "outro", verified: true, cites: [],
    en: "Dr. Petrova, thank you for that... wow, that was an absolutely fascinating look at the future, especially the work on cancer. And thank you all for listening... you know, stay curious until we meet again!",
    hi: "डॉक्टर पेट्रोवा, तो भविष्य पर आपके बहुत दिलचस्प नज़रिया के लिए शुक्रिया, खासकर कैंसर पर आपके काम के लिए। और सुनने वाले आप सभी का भी शुक्रिया... जब तक हम फिर मिलते हैं, जिज्ञासु रहिए!",
    ta: "டாக்டர் பெட்ரோவா, எதிர்காலம் பத்தின உங்க ஃபேசினேட்டிங் இன்சைட்ஸ் சொன்னதுக்கு ரொம்ப நன்றி... குறிப்பா கேன்சர் பத்தின உங்க வேலைக்கு. எல்லாரும் கேட்டுட்டு இருக்கறதுக்கு நன்றி... குறியா இருங்க!",
  },
];

export function mrnaTurns(langCode: string): TranscriptTurn[] {
  const key = langCode.startsWith("hi") ? "hi" : langCode.startsWith("ta") ? "ta" : "en";
  const canonical = T.map((t) => t.en);
  return T.map((t, idx) => ({
    idx,
    speaker: t.speaker,
    speaker_name: t.speaker === "host" ? MRNA_CAST.host.name : MRNA_CAST.expert.name,
    text: canonical[idx],
    spoken: (t as any)[key] as string,
    move: t.move,
    verified: t.verified,
    citation_numbers: t.cites,
  }));
}

export const MRNA_TOPIC = "how mRNA vaccines work";
