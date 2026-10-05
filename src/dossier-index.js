const CALENDAR_OR_CLOCK = /\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|spring|summer|autumn|fall|winter|christmas|today|tonight|tomorrow|yesterday|morning|afternoon|evening|night|nighttime|nightfall|midnight|noon|dawn|sunrise|sunset|daytime|weekday|weekend|b\.?c\.?e\.?|a\.?d\.?)\b/i;
const CLOCK_OR_YEAR = /\b(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|(?:1[0-9]{3}|2[0-9]{3}))\b/i;
const QUANTIFIED_DURATION = /\b(?:(?:an?|one|two|three|four|five|six|seven|eight|nine|ten|several|few|many|\d+(?:\.\d+)?)\s+|matter of )(?:seconds?|minutes?|hours?|days?|nights?|weeks?|months?|years?|decades?|centuries?)\b/i;
const RELATIVE_TIME = /\b(?:before|after|later|earlier|previous(?:ly)?|next|since|until|during|while|meanwhile|simultaneous(?:ly)?|subsequent(?:ly)?|immediately|shortly|recently|eventually|then|finally|ago|daily|nightly|weekly|monthly|yearly|now|present day|current scene|same (?:day|night|time)|time passes|passage of time|over time|long-term|in the aftermath|as soon as)\b/i;
const TEMPORAL_ACTION = /\b(?:begins?|began|starts?|started|ends?|ended|continues?|continued|returns?|returned|follows?|followed|precedes?|preceded|occurs?|occurred|takes place|spans?|elapsed|deadline|duration|timing|coincides?|quickly)\b/i;

// Dossiers remain untouched. This deliberately conservative display filter
// keeps only notes that make an inspectable temporal claim rather than broad
// plot commentary that happened to be returned in a timeline field.
export function isTemporalDossierObservation(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return Boolean(text && (
    CALENDAR_OR_CLOCK.test(text)
    || CLOCK_OR_YEAR.test(text)
    || QUANTIFIED_DURATION.test(text)
    || RELATIVE_TIME.test(text)
    || TEMPORAL_ACTION.test(text)
  ));
}
