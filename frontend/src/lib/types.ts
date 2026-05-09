export type UserProfile = {
  full_name: string | null;
  dob: string | null;
  phone: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  postal_code: string | null;
};

export type AuthUser = {
  id: number;
  username: string;
  email: string;
  profile: UserProfile;
};

export type DashboardSummary = {
  total_income: number;
  total_expenses: number;
  net_balance: number;
  total_balance: number;
  monthly_income: number;
  monthly_expenses: number;
  monthly_savings: number;
  savings_rate: number;
  forecast_next_month: number;
};

export type DashboardActivity = {
  id: string | number;
  transaction_type: string;
  date: string;
  amount: number;
  primary_label: string;
  secondary_label: string;
  description?: string | null;
  payment_method?: string | null;
  source?: string | null;
};

export type BudgetWarning = {
  budgetId: number;
  category: string;
  status: "warning" | "exceeded";
  percentage: number;
  spent: number;
  limit: number;
};

export type InsightSummary = {
  id: number;
  title: string;
  summary: string;
  type: string;
};

export type DashboardResponse = {
  summary: DashboardSummary;
  income_vs_expenses: Array<{
    month: string;
    income: number;
    expenses: number;
  }>;
  category_breakdown: Array<{
    category: string;
    total: number;
  }>;
  recent_activity: DashboardActivity[];
  budget_warnings: BudgetWarning[];
  ai_insights: InsightSummary[];
};

export type DashboardTrend = {
  month: string;
  income: number;
  expenses: number;
  savings: number;
};

export type MonthlySummary = {
  month: string;
  income: number;
  expenses: number;
  savings: number;
  savingsRate: number;
  totalBalance: number;
  categorySpending: Array<{ category: string; total: number }>;
  topMerchants: Array<{ merchant: string; total: number }>;
  budgetWarnings: BudgetWarning[];
};

export type Budget = {
  id: number;
  category_id: number;
  category_name: string;
  monthly_limit: number;
  period: string;
  currency: string;
  country: string;
  spent: number;
  remaining: number;
  percentage: number;
  status: "safe" | "warning" | "exceeded";
};

export type Goal = {
  id: number;
  name: string;
  targetAmount: number;
  currentAmount: number;
  currency: string;
  country: string;
  targetDate: string | null;
  progressPercentage: number;
  requiredMonthlySavings: number;
  createdAt: string | null;
};

export type Category = {
  id: number;
  name: string;
};

export type DashboardOverviewResponse = {
  dashboard: DashboardResponse;
  monthlySummary: MonthlySummary;
  trends: DashboardTrend[];
  budgets: Budget[];
  goals: Goal[];
  categories: Category[];
};

export type Transaction = {
  id: string;
  userId: string;
  accountId: string | null;
  receiptId: number | null;
  providerTransactionId: string | null;
  amount: number;
  currency: string;
  country: string;
  type: "income" | "expense";
  merchant: string | null;
  description: string | null;
  category: string;
  subcategory: string | null;
  paymentMethod: string;
  source: string;
  date: string;
  createdAt: string | null;
  primary_label: string;
  secondary_label: string | null;
  transaction_type: string;
  payment_method: string;
};

export type BankProvider = {
  key: string;
  label: string;
  countries: string[];
};

export type BankAccount = {
  id: number;
  accountId: string;
  provider: string;
  providerAccountId: string;
  name: string;
  mask: string | null;
  institutionName: string | null;
  accountType: string | null;
  balance: number;
  availableBalance: number;
  currency: string;
  country: string;
  status: string;
  lastSyncedAt: string | null;
};

export type ReceiptItem = {
  id: number;
  name: string;
  quantity: number;
  unitPrice: number | null;
  totalPrice: number;
  category: string | null;
};

export type Receipt = {
  id: number;
  merchant: string | null;
  amount: number | null;
  currency: string;
  country: string;
  date: string | null;
  status: string;
  rawText: string;
  cleanedText: string;
  transaction: Transaction | null;
  items: ReceiptItem[];
  createdAt: string | null;
};

export type AiInsight = {
  id: number;
  type: string;
  title: string;
  summary: string;
  payload: {
    recommendations?: string[];
    risks?: string[];
    [key: string]: unknown;
  };
  createdAt: string | null;
};

export type RecurringPattern = {
  id: number;
  description: string;
  amount: number;
  transaction_type: "income" | "expense";
  category_id: number | null;
  category_name: string | null;
  frequency: string;
  avg_gap_days: number | null;
  occurrence_count: number;
  status: "suggested" | "confirmed" | "dismissed";
  auto_create: boolean;
  last_seen_date: string | null;
  next_expected_date: string | null;
  created_at: string | null;
};

export type Subscription = {
  id: number;
  displayName: string;
  merchant: string | null;
  amount: number;
  currency: string;
  country: string;
  category: string;
  frequency: string;
  monthlyCost: number;
  annualCost: number;
  source: string;
  status: "active" | "cancel_requested" | "cancelled" | "ignored";
  occurrenceCount: number;
  firstSeenDate: string | null;
  lastSeenDate: string | null;
  nextExpectedDate: string | null;
  cancellationRequestedAt: string | null;
  cancellationNotes: string;
  updatedAt: string | null;
};

export type BillNegotiation = {
  id: number;
  providerName: string;
  billType: string;
  currentAmount: number;
  targetAmount: number | null;
  negotiatedAmount: number | null;
  estimatedSavings: number;
  successFeePercentage: number;
  currency: string;
  country: string;
  status: "requested" | "negotiating" | "succeeded" | "failed" | "cancelled";
  notes: string;
  createdAt: string | null;
  updatedAt: string | null;
};

export type NetWorthItem = {
  id: number;
  name: string;
  itemType: "asset" | "liability";
  category: string;
  balance: number;
  currency: string;
  country: string;
  source: string;
  notes: string;
  asOfDate: string | null;
  updatedAt: string | null;
};

export type NetWorthAccountItem = Omit<NetWorthItem, "id"> & {
  id: string;
};

export type NetWorthTotal = {
  currency: string;
  assets: number;
  liabilities: number;
  netWorth: number;
};

export type CreditProfile = {
  id: number;
  score: number;
  bureau: string;
  scoringModel: string;
  status: string;
  notes: string;
  reportedAt: string;
  createdAt: string | null;
};

export type SharedAccessGrant = {
  id: number;
  inviteEmail: string;
  role: "viewer" | "editor";
  status: "invited" | "accepted" | "revoked";
  createdAt: string | null;
  revokedAt: string | null;
};

export type FinancialToolsOverview = {
  subscriptions: Subscription[];
  subscriptionSummary: {
    activeCount: number;
    monthlyCost: number;
    annualCost: number;
  };
  billNegotiations: BillNegotiation[];
  billSummary: {
    openCount: number;
    estimatedSavings: number;
  };
  netWorth: {
    totalsByCurrency: NetWorthTotal[];
    manualItems: NetWorthItem[];
    accountItems: NetWorthAccountItem[];
  };
  creditProfile: CreditProfile | null;
  creditHistory: CreditProfile[];
  sharedAccess: SharedAccessGrant[];
};
