import { useState, type ReactNode } from "react";

import { PendingButton } from "../components/ui";
import { PageTitle } from "./PageTitle";

// docs/04-web-app.md, "onboarding": a short wizard that can be left and resumed.
// Navigation between steps works; saving each step is wired in Layer 1.
// Step 1 lists the scopes from ADR-010; step 4 follows ADR-014 (backup numbers).
const steps: { title: string; body: ReactNode }[] = [
  {
    title: "חיבור חשבון Google",
    body: (
      <>
        <p className="mb-2">לפני ההפניה לגוגל — אילו הרשאות מתבקשות ולמה:</p>
        <ul className="list-disc space-y-1 ps-5 text-sm">
          <li>קריאת מיילים — כדי לזהות בקשות לפגישה. בלי הרשאה למחוק או לשנות מיילים.</li>
          <li>שליחת מיילים — רק תשובות שאישרת, באותה שיחה.</li>
          <li>אירועים ביומנים שבבעלותך — כדי לבדוק מתי אתה פנוי ולקבוע פגישות עם Meet.</li>
        </ul>
        <div className="mt-3">
          <PendingButton tone="primary">חיבור ל-Google</PendingButton>
        </div>
      </>
    ),
  },
  {
    title: "אימות מספר הווטסאפ",
    body: <p>הסוכן ישלח קוד חד-פעמי למספר שלך. רק מהמספר הזה הסוכן יקבל פקודות.</p>,
  },
  {
    title: "שעות עבודה",
    body: <p>ימים ושעות עבודה, ושעת סיום יום העבודה. אחריה פעולות שלא אושרו פגות.</p>,
  },
  {
    title: "עצירת חירום",
    body: (
      <p>
        קוד עצירה (מוזן פעמיים ולא מוצג שוב), ומספר גיבוי אחד או שניים — למשל הטלפון של בן או בת הזוג. כל מספר
        גיבוי מאומת בקוד חד-פעמי. אם הטלפון שלך אבד, שולחים את הקוד ממספר גיבוי.
      </p>
    ),
  },
  {
    title: "אימות לבקשות חריגות",
    body: <p>קוד אישי (PIN) או שאלה סודית. נדרש לפני פעולות כמו פנייה לנמען חדש או ביטול של יותר משתי פגישות.</p>,
  },
  {
    title: "סיכום",
    body: <p>איך מדברים עם הסוכן בווטסאפ: מבקשים לקבוע, מעבירים הודעות מלקוחות, ומאשרים בכפתור.</p>,
  },
];

export function OnboardingPage() {
  const [index, setIndex] = useState(0);
  const step = steps[index] ?? steps[0];
  const isLast = index === steps.length - 1;

  return (
    <section>
      <PageTitle>הגדרה ראשונית</PageTitle>
      <p className="mb-4 text-sm text-slate-600" aria-live="polite">
        שלב {index + 1} מתוך {steps.length}
      </p>
      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-lg font-semibold">{step?.title}</h2>
        <div className="text-slate-700">{step?.body}</div>
      </div>
      <div className="flex justify-between">
        <button
          type="button"
          onClick={() => setIndex((i) => i - 1)}
          disabled={index === 0}
          className="rounded-lg border border-slate-300 px-4 py-2 disabled:opacity-40"
        >
          הקודם
        </button>
        {isLast ? (
          <PendingButton tone="primary">סיום</PendingButton>
        ) : (
          <button type="button" onClick={() => setIndex((i) => i + 1)} className="rounded-lg bg-blue-700 px-4 py-2 text-white">
            הבא
          </button>
        )}
      </div>
    </section>
  );
}
