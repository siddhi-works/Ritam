export interface QuestionLink {
  label: string;
  href: string;
}

export interface Question {
  q: string;
  a: string[];
  links: QuestionLink[];
}

export interface QuestionGroup {
  title: string;
  questions: Question[];
}

const RBI_CARDS: QuestionLink = {
  label: "RBI Master Direction on credit cards",
  href: "https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12300",
};
const RBI_COMPLAINT: QuestionLink = { label: "RBI complaint portal", href: "https://cms.rbi.org.in/" };
const RBI_FRAUD: QuestionLink = {
  label: "RBI rules on unauthorised transactions",
  href: "https://rbi.org.in/Scripts/NotificationUser.aspx?Id=11040",
};
const CYBERCRIME: QuestionLink = { label: "National cybercrime portal", href: "https://cybercrime.gov.in/" };
const AUDIT: QuestionLink = { label: "Get a report on your card", href: "/#start" };

// Rules quoted from the RBI Master Direction (updated 7 March 2024) and the 2017 customer
// protection circular. Anything that depends on the bank is marked as such.
export const QUESTION_GROUPS: QuestionGroup[] = [
  {
    title: "Fees and charges",
    questions: [
      {
        q: "Can my bank change fees whenever it wants?",
        a: [
          "No. Changes in charges can only apply from a future date, with at least one month's notice.",
          "If a change works against you, you can close the card without any extra charge for closing it, once your dues are paid.",
          "The bank also can't charge you anything that wasn't explicitly told to you when the card was issued.",
        ],
        links: [RBI_CARDS, AUDIT],
      },
      {
        q: "Is a 'lifetime free' card really free?",
        a: [
          "It usually means no joining or annual fee. Interest, late payment charges, cash withdrawal fees and the foreign currency markup still apply.",
          "Check the card's MITC (Most Important Terms and Conditions) for the full list; promotional pages often leave these out.",
        ],
        links: [AUDIT],
      },
      {
        q: "Where can I see every charge on my card?",
        a: [
          "In the card's MITC and the bank's schedule of charges, usually linked from the card's page on the bank's website.",
          "If a comparison site shows a different figure, trust the bank's latest MITC.",
        ],
        links: [AUDIT, RBI_CARDS],
      },
    ],
  },
  {
    title: "Bills, interest and repayment",
    questions: [
      {
        q: "What happens if I pay only the minimum amount due?",
        a: [
          "You avoid the late payment charge, but interest is charged on the rest of the balance, and most banks also stop the interest-free period on new purchases until you clear the full amount.",
          "RBI requires the minimum amount due to be set so the balance doesn't keep growing on its own, and unpaid charges and taxes can't be added to the amount interest is charged on.",
        ],
        links: [RBI_CARDS],
      },
      {
        q: "When does a payment count as late?",
        a: [
          "Late payment charges apply only when the payment is more than three days past the due date. Once that happens, the days are counted from the due date itself.",
          "The same three-day rule applies before a bank can report you as late to credit bureaus.",
        ],
        links: [RBI_CARDS],
      },
      {
        q: "What is the interest-free period?",
        a: [
          "The time from a purchase to the payment due date. It only applies if you pay the entire outstanding amount by the due date.",
          "Cash withdrawals are usually charged interest from the day you withdraw; check your card's MITC.",
        ],
        links: [AUDIT],
      },
      {
        q: "Can I change my billing date?",
        a: ["Yes. Banks must let you change your billing cycle at least once. Ask through the bank's app or customer care."],
        links: [RBI_CARDS],
      },
      {
        q: "I overpaid or got a refund. How do I get the money back?",
        a: [
          "The extra amount sits as a credit balance on the card. If you ask the bank to move it to your bank account, it must do so within three working days.",
        ],
        links: [RBI_CARDS],
      },
    ],
  },
  {
    title: "Cards you didn't ask for",
    questions: [
      {
        q: "I got a card or an upgrade I never asked for.",
        a: [
          "Unsolicited cards and upgrades are prohibited. If you were billed for one, the bank must reverse the charges and pay you a penalty of twice the amount reversed.",
          "You can also complain to the RBI Ombudsman.",
        ],
        links: [RBI_CARDS, RBI_COMPLAINT],
      },
      {
        q: "I never activated my new card.",
        a: [
          "If a card isn't activated for more than 30 days, the bank must ask for your consent by OTP. Without it, the bank must close the card at no cost within seven working days.",
        ],
        links: [RBI_CARDS],
      },
    ],
  },
  {
    title: "Closing a card",
    questions: [
      {
        q: "How do I close my credit card?",
        a: [
          "Ask the bank through any of its channels: app, website, email or customer care. Once your dues are paid, the bank must close the account within seven working days.",
          "Redeem reward points first; what happens to them on closure depends on the bank.",
        ],
        links: [RBI_CARDS],
      },
    ],
  },
  {
    title: "Fraud and disputes",
    questions: [
      {
        q: "Someone used my card without permission.",
        a: [
          "Block the card straight away in the bank's app or through customer care, and report the transaction to the bank. For online fraud, also call 1930 or report on the cybercrime portal.",
          "Under RBI's rules, if the fault lies elsewhere and you tell the bank within three working days of its alert, your liability is zero. Reporting later can make you partly liable.",
        ],
        links: [RBI_FRAUD, CYBERCRIME],
      },
      {
        q: "There's a wrong charge on my bill.",
        a: [
          "Raise it with the bank in writing and keep the reference number. The bank must give you an explanation, with documents where relevant, within 30 days.",
        ],
        links: [RBI_CARDS],
      },
      {
        q: "The bank didn't solve my complaint.",
        a: [
          "Escalate to the bank's grievance or nodal officer (listed on its website). If there's no reply within 30 days, or you're not satisfied with it, complain to the RBI Ombudsman online.",
        ],
        links: [RBI_COMPLAINT],
      },
    ],
  },
  {
    title: "Credit score",
    questions: [
      {
        q: "Does checking my own credit score lower it?",
        a: [
          "No. Checking your own score doesn't affect it. Applying for a card or loan leads the lender to check your report, and many applications in a short time can.",
        ],
        links: [],
      },
      {
        q: "My credit report has a mistake.",
        a: [
          "Raise a dispute with the credit bureau that issued the report (CIBIL, Experian, Equifax or CRIF High Mark) and tell your bank. If the error came from the bank, the bank must correct it with the bureau.",
        ],
        links: [RBI_COMPLAINT],
      },
    ],
  },
];

export const ASK_THE_BANK = [
  "Whether you'll be approved, or what credit limit you'll get",
  "Your own statement, balance or reward points",
  "Offers that are only shown inside the bank's app",
];
