import { useEffect, useRef, useState } from "react";
import type { Data, Layout } from "plotly.js";

type Figure = { data: Data[]; layout: Partial<Layout> };
type Dashboard = {
  figures: Figure[];
  analyses: Record<string, { result: Record<string, unknown> }>;
  unavailable: Record<string, string>;
  currency: string;
};
type Meta = {
  id: string;
  version: number;
  meta: {
    sheets: Record<string, { columns: string[]; rows: number }>;
    state: string;
  };
};
const fields: Record<string, string> = {
  transaction_date: "تاریخ فروش",
  sales_amount: "مبلغ فروش هر ردیف",
  order_id: "شناسه سفارش",
  customer_id: "شناسه مشتری",
  product_id: "شناسه محصول",
  product_name: "نام محصول",
  sales_quantity: "تعداد",
  cost: "هزینه",
  discount: "مبلغ تخفیف",
  text: "متن بازخورد",
  region: "منطقه",
  currency: "واحد پول",
};
const titles: Record<string, string> = {
  summary: "خلاصه فروش",
  trend: "روند فروش",
  products: "عملکرد محصولات",
  customers: "عملکرد مشتریان",
  rfm: "تازگی، تکرار و مبلغ خرید",
  retention: "ماندگاری مشتریان",
  basket: "خرید محصولات همراه",
  regions: "فروش مناطق",
  correlation: "همبستگی متغیرها",
};
const statuses: Record<string, string> = {
  queued: "در صف",
  running: "در حال پردازش",
  completed: "پایان‌یافته",
  failed: "ناموفق",
  cancelled: "لغوشده",
};

function Chart({ figure }: { figure: Figure }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let disposed = false;
    let plotly: (typeof import("plotly.js-dist-min"))["default"] | undefined;
    const target = element.current;
    void import("plotly.js-dist-min").then((module) => {
      plotly = module.default;
      if (!disposed && target)
        void plotly.newPlot(
          target,
          figure.data,
          { ...figure.layout, autosize: true },
          { responsive: true, displaylogo: false },
        );
    });
    return () => {
      disposed = true;
      if (plotly && target) plotly.purge(target);
    };
  }, [figure]);
  return <div ref={element} className="chart" aria-label="نمودار تحلیل فروش" />;
}

function Result({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>—</span>;
  if (
    typeof value === "object" &&
    !Array.isArray(value) &&
    "message" in value &&
    typeof value.message === "string"
  ) {
    return (
      <>
        <p className="notice">{value.message}</p>
        <details>
          <summary>شواهد، پیشنهادها و محدودیت‌ها</summary>
          <pre>{JSON.stringify(value, null, 2)}</pre>
        </details>
      </>
    );
  }
  if (
    Array.isArray(value) &&
    value.length &&
    value.every(
      (item) => item && typeof item === "object" && !Array.isArray(item),
    )
  ) {
    const rows = value as Record<string, unknown>[];
    const columns = Array.from(new Set(rows.flatMap(Object.keys)));
    return (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((key) => (
                <th key={key}>{key}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((row, index) => (
              <tr key={index}>
                {columns.map((key) => (
                  <td key={key}>
                    {typeof row[key] === "object"
                      ? JSON.stringify(row[key])
                      : String(row[key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > 100 && <p>صد ردیف نخست نمایش داده شده است.</p>}
      </div>
    );
  }
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export default function App() {
  const [key, setKey] = useState("");
  const [dataset, setDataset] = useState<Meta | null>(null);
  const [sheet, setSheet] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [currency, setCurrency] = useState("IRT");
  const [grain, setGrain] = useState("line_item");
  const [definition, setDefinition] = useState("");
  const [basis, setBasis] = useState("net_after_discount");
  const [costBasis, setCostBasis] = useState("unavailable");
  const [calendar, setCalendar] = useState("gregorian");
  const [dateFormat, setDateFormat] = useState("%Y-%m-%d");
  const [confirmed, setConfirmed] = useState(false);
  const [cleanConfirmed, setCleanConfirmed] = useState(false);
  const [nulls, setNulls] = useState("preserve");
  const [duplicates, setDuplicates] = useState("keep");
  const [question, setQuestion] = useState(
    "کدام محصولات بیشترین فروش را دارند؟",
  );
  const [useLLM, setUseLLM] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [result, setResult] = useState<unknown>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [customer, setCustomer] = useState("");
  const [product, setProduct] = useState("");
  const [decimal, setDecimal] = useState(".");
  const [thousands, setThousands] = useState(",");
  const [dimension, setDimension] = useState("");
  const [leftKey, setLeftKey] = useState("");
  const [rightKey, setRightKey] = useState("");
  const [dimensionColumn, setDimensionColumn] = useState("");
  const [joinConfirmed, setJoinConfirmed] = useState(false);
  const [advanced, setAdvanced] = useState("forecast");
  const [horizon, setHorizon] = useState(7);
  const [priceChange, setPriceChange] = useState(0);
  const [volumeChange, setVolumeChange] = useState(0);
  const [discountRate, setDiscountRate] = useState(0);
  const [discountPoints, setDiscountPoints] = useState(0);
  const [scenarioConfirmed, setScenarioConfirmed] = useState(false);
  const [taskId, setTaskId] = useState("");
  const stop = useRef(false);
  useEffect(() => {
    stop.current = false;
    return () => {
      stop.current = true;
    };
  }, []);

  async function api(path: string, method = "GET", body?: unknown) {
    const form = body instanceof FormData;
    const response = await fetch("/api" + path, {
      method,
      headers: {
        "X-API-Key": key,
        ...(!form && body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
      },
      body: body === undefined ? undefined : form ? body : JSON.stringify(body),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text);
    }
    return await response.json();
  }
  async function action(fn: () => Promise<void>) {
    setError("");
    setBusy(true);
    setProgress("در حال اجرا");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress("");
    }
  }
  async function task(path: string, body: unknown) {
    const receipt = await api(path, "POST", body);
    setTaskId(receipt.task_id);
    const deadline = Date.now() + 10 * 60_000;
    while (Date.now() < deadline && !stop.current) {
      const status = await api("/tasks/" + receipt.task_id);
      setProgress(
        `وضعیت پردازش: ${statuses[status.status] ?? status.status} · ${Number(status.progress).toLocaleString("fa-IR")}٪`,
      );
      if (status.status === "completed") return status.result.output;
      if (status.status === "failed" || status.status === "cancelled")
        throw new Error(status.error ?? "پردازش لغو شد.");
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error(
      "انتظار پایان یافت. شناسه پردازش را برای بررسی بعدی نگه دارید: " +
        receipt.task_id,
    );
  }
  const filters = () => ({
    ...(start ? { start } : {}),
    ...(end ? { end } : {}),
    ...(customer ? { customer_id: customer } : {}),
    ...(product ? { product_id: product } : {}),
    limit: 20,
  });
  async function refresh() {
    if (dataset) setDataset(await api("/jobs/" + dataset.id));
  }
  function chooseSheet(value: string) {
    setSheet(value);
    setMapping({});
    setConfirmed(false);
  }
  async function upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    const data = (await api("/upload", "POST", form)) as Meta;
    setDataset(data);
    setSheet(Object.keys(data.meta.sheets)[0]);
    setMapping({});
    setDashboard(null);
    setResult(null);
    setConfirmed(false);
    setCleanConfirmed(false);
  }
  async function exportFile(format: string) {
    if (!dataset) return;
    const response = await fetch(`/api/export/${dataset.id}?format=${format}`, {
      headers: { "X-API-Key": key },
    });
    if (!response.ok) throw new Error(await response.text());
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `sales-report.${format}`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main>
      <h1>راهنمای تحلیل فروش</h1>
      <p className="muted">
        فایل فروش را بررسی کنید، معنای ستون‌ها را تأیید کنید و نتیجه را همراه با
        منبع ببینید.
      </p>
      <section>
        <h2>اتصال و دریافت فایل</h2>
        <label className="key">
          کلید دسترسی محلی
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </label>
        <p className="small muted">
          کلید فقط در حافظه این صفحه می‌ماند. با بستن صفحه پاک می‌شود.
        </p>
        <label>
          فایل فروش
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            disabled={busy || !key}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void action(() => upload(file));
            }}
          />
        </label>
        {dataset && (
          <p className="notice">
            فایل دریافت شد. شناسه مجموعه داده:{" "}
            <span dir="ltr">{dataset.id}</span>
          </p>
        )}
      </section>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {busy && (
        <div role="status">
          <p>{progress}</p>
          <progress />
          {taskId && (
            <button
              className="secondary"
              onClick={() =>
                void api("/tasks/" + taskId + "/cancel", "POST")
                  .then(() => setProgress("درخواست لغو ثبت شد."))
                  .catch((e) => setError(String(e)))
              }
            >
              درخواست لغو
            </button>
          )}
        </div>
      )}
      {dataset && (
        <>
          <section>
            <h2>معنای ستون‌ها</h2>
            <div className="grid">
              <label>
                برگه داده
                <select
                  value={sheet}
                  onChange={(e) => chooseSheet(e.target.value)}
                >
                  {Object.keys(dataset.meta.sheets).map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label>
                هر ردیف نماینده چیست؟
                <select
                  value={grain}
                  onChange={(e) => setGrain(e.target.value)}
                >
                  <option value="line_item">یک محصول در سفارش</option>
                  <option value="order">یک سفارش کامل</option>
                </select>
              </label>
              <label>
                واحد پول
                <input
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                />
              </label>
              <label>
                تعریف مبلغ فروش
                <select
                  value={basis}
                  onChange={(e) => setBasis(e.target.value)}
                >
                  <option value="net_after_discount">
                    فروش پس از کسر تخفیف
                  </option>
                  <option value="gross_before_discount">
                    فروش پیش از کسر تخفیف
                  </option>
                </select>
              </label>
              <label>
                تعریف هزینه
                <select
                  value={costBasis}
                  onChange={(e) => setCostBasis(e.target.value)}
                >
                  <option value="unavailable">هزینه معتبر ندارم</option>
                  <option value="line_total">هزینه کل همان ردیف</option>
                  <option value="per_unit">هزینه هر واحد محصول</option>
                </select>
              </label>
              <label>
                تقویم ورودی
                <select
                  value={calendar}
                  onChange={(e) => setCalendar(e.target.value)}
                >
                  <option value="gregorian">میلادی</option>
                  <option value="jalali">شمسی</option>
                </select>
              </label>
              <label>
                قالب تاریخ
                <input
                  dir="ltr"
                  value={dateFormat}
                  onChange={(e) => setDateFormat(e.target.value)}
                />
              </label>
            </div>
            <div className="grid mt-4">
              {Object.entries(fields).map(([name, label]) => (
                <label key={name}>
                  {label}
                  <select
                    value={mapping[name] ?? ""}
                    onChange={(e) => {
                      setMapping({ ...mapping, [name]: e.target.value });
                      setConfirmed(false);
                    }}
                  >
                    <option value="">انتخاب نشده</option>
                    {(dataset.meta.sheets[sheet]?.columns ?? []).map(
                      (column) => (
                        <option key={column}>{column}</option>
                      ),
                    )}
                  </select>
                </label>
              ))}
            </div>
            <label className="mt-4">
              مبلغ فروش شامل چه مواردی است؟
              <textarea
                placeholder="وضعیت مالیات، مرجوعی، ارسال و تخفیف را توضیح دهید."
                value={definition}
                onChange={(e) => setDefinition(e.target.value)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              معنای ستون‌ها، واحد پول و تعریف فروش را بررسی و تأیید کرده‌ام.
            </label>
            <div className="actions">
              <button
                disabled={busy || !confirmed}
                onClick={() =>
                  void action(async () => {
                    await api("/mapping/" + dataset.id, "POST", {
                      sheet,
                      columns: Object.fromEntries(
                        Object.entries(mapping).filter(([, value]) => value),
                      ),
                      grain,
                      currency,
                      sales_definition: definition,
                      sales_basis: basis,
                      cost_basis: costBasis,
                      date_calendar: calendar,
                      date_format: dateFormat,
                      confirmed,
                    });
                    await refresh();
                    setResult({
                      message:
                        "نگاشت ثبت شد. اکنون سیاست پاک‌سازی را انتخاب کنید.",
                    });
                  })
                }
              >
                ثبت نگاشت
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void action(async () =>
                    setResult(await api("/schema/" + dataset.id)),
                  )
                }
              >
                بررسی کیفیت و پیشنهاد نگاشت
              </button>
            </div>
          </section>
          {Object.keys(dataset.meta.sheets).length > 1 && (
            <section>
              <h2>اتصال برگه اطلاعات تکمیلی</h2>
              <p className="muted">
                شناسه برگه تکمیلی باید یکتا باشد تا جمع فروش افزایش پیدا نکند.
                این نسخه یک برگه تکمیلی را می‌پذیرد.
              </p>
              <div className="grid">
                <label>
                  برگه تکمیلی
                  <select
                    value={dimension}
                    onChange={(e) => setDimension(e.target.value)}
                  >
                    <option value="">انتخاب کنید</option>
                    {Object.keys(dataset.meta.sheets)
                      .filter((name) => name !== sheet)
                      .map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                  </select>
                </label>
                <label>
                  ستون اتصال در فروش
                  <select
                    value={leftKey}
                    onChange={(e) => setLeftKey(e.target.value)}
                  >
                    <option value="">انتخاب کنید</option>
                    {dataset.meta.sheets[sheet]?.columns.map((name) => (
                      <option key={name}>{name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  شناسه در برگه تکمیلی
                  <select
                    value={rightKey}
                    onChange={(e) => setRightKey(e.target.value)}
                  >
                    <option value="">انتخاب کنید</option>
                    {dataset.meta.sheets[dimension]?.columns.map((name) => (
                      <option key={name}>{name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  ستون اطلاعاتی برای افزودن
                  <select
                    value={dimensionColumn}
                    onChange={(e) => setDimensionColumn(e.target.value)}
                  >
                    <option value="">انتخاب کنید</option>
                    {dataset.meta.sheets[dimension]?.columns
                      .filter((name) => name !== rightKey)
                      .map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                  </select>
                </label>
              </div>
              <label className="check">
                <input
                  type="checkbox"
                  checked={joinConfirmed}
                  onChange={(e) => setJoinConfirmed(e.target.checked)}
                />
                ارتباط این دو برگه را تأیید می‌کنم.
              </label>
              <button
                disabled={busy || !joinConfirmed}
                onClick={() =>
                  void action(async () => {
                    setResult(
                      await api("/relationships/" + dataset.id, "POST", {
                        sheet: dimension,
                        left_on: leftKey,
                        right_on: rightKey,
                        columns: [dimensionColumn],
                        cardinality: "many_to_one",
                        allow_unmatched: false,
                        confirmed: true,
                      }),
                    );
                    await refresh();
                  })
                }
              >
                ثبت ارتباط
              </button>
            </section>
          )}
          <section>
            <h2>سیاست پاک‌سازی</h2>
            <div className="grid">
              <label>
                مقادیر عددی خالی
                <select
                  value={nulls}
                  onChange={(e) => setNulls(e.target.value)}
                >
                  <option value="preserve">خالی بمانند و گزارش شوند</option>
                  <option value="error">پردازش متوقف شود</option>
                  <option value="zero">با تأیید من صفر شوند</option>
                </select>
              </label>
              <label>
                ردیف‌های کاملاً تکراری
                <select
                  value={duplicates}
                  onChange={(e) => setDuplicates(e.target.value)}
                >
                  <option value="keep">حفظ و گزارش شوند</option>
                  <option value="drop_exact">حذف با ثبت شماره ردیف</option>
                </select>
              </label>
              <label>
                جداکننده اعشار
                <select
                  value={decimal}
                  onChange={(e) => setDecimal(e.target.value)}
                >
                  <option value=".">نقطه</option>
                  <option value=",">ویرگول</option>
                </select>
              </label>
              <label>
                جداکننده هزارگان
                <select
                  value={thousands}
                  onChange={(e) => setThousands(e.target.value)}
                >
                  <option value=",">ویرگول</option>
                  <option value=".">نقطه</option>
                  <option value="٬">هزارگان فارسی</option>
                  <option value="">ندارد</option>
                </select>
              </label>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={cleanConfirmed}
                onChange={(e) => setCleanConfirmed(e.target.checked)}
              />
              اثر سیاست را بررسی کرده‌ام. فایل اصلی حفظ شود و تغییرات ثبت شوند.
            </label>
            <button
              disabled={
                busy || !cleanConfirmed || dataset.meta.state === "uploaded"
              }
              onClick={() =>
                void action(async () => {
                  setResult(
                    await api("/clean/" + dataset.id, "POST", {
                      numeric_nulls: nulls,
                      duplicates,
                      decimal_separator: decimal,
                      thousands_separator: thousands,
                      invalid_values: "error",
                      confirmed: true,
                    }),
                  );
                  await refresh();
                  setDashboard(null);
                })
              }
            >
              ایجاد نسخه پاک‌سازی‌شده
            </button>
          </section>
          {dataset.meta.state === "cleaned" && (
            <>
              <section>
                <h2>تحلیل فروش</h2>
                <div className="grid">
                  <label>
                    از تاریخ میلادی
                    <input
                      type="date"
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </label>
                  <label>
                    تا تاریخ میلادی
                    <input
                      type="date"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </label>
                  <label>
                    شناسه مشتری
                    <input
                      value={customer}
                      onChange={(e) => setCustomer(e.target.value)}
                    />
                  </label>
                  <label>
                    شناسه محصول
                    <input
                      value={product}
                      onChange={(e) => setProduct(e.target.value)}
                    />
                  </label>
                </div>
                <div className="actions">
                  <button
                    disabled={busy}
                    onClick={() =>
                      void action(async () =>
                        setDashboard(
                          (await task(
                            "/analyze/" + dataset.id,
                            filters(),
                          )) as Dashboard,
                        ),
                      )
                    }
                  >
                    محاسبه داشبورد
                  </button>
                  {["csv", "xlsx", "json", "html"].map((format) => (
                    <button
                      key={format}
                      className="secondary"
                      disabled={busy}
                      onClick={() => void action(() => exportFile(format))}
                    >
                      دریافت {format.toUpperCase()}
                    </button>
                  ))}
                </div>
                {dashboard && (
                  <>
                    <p>واحد پول: {dashboard.currency}</p>
                    {dashboard.figures.map((figure, index) => (
                      <Chart key={index} figure={figure} />
                    ))}
                    {Object.entries(dashboard.analyses).map(
                      ([name, analysis]) => (
                        <details key={name}>
                          <summary>{titles[name] ?? name}</summary>
                          <Result value={analysis.result} />
                        </details>
                      ),
                    )}
                    {Object.keys(dashboard.unavailable).length > 0 && (
                      <details>
                        <summary>تحلیل‌های فاقد داده کافی</summary>
                        <Result value={dashboard.unavailable} />
                      </details>
                    )}
                  </>
                )}
              </section>
              <section>
                <h2>پرسش از داده‌ها</h2>
                <label>
                  پرسش شما
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </label>
                <p className="small muted">
                  برای پرسش‌هایی مثل «ماه گذشته»، بازه دقیق را در فیلترهای بالا
                  انتخاب کنید.
                </p>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={useLLM}
                    onChange={(e) => setUseLLM(e.target.checked)}
                  />
                  برای انتخاب ابزار از مدل محلی نصب‌شده کمک بگیر.
                </label>
                <button
                  disabled={busy}
                  onClick={() =>
                    void action(async () =>
                      setResult(
                        await task("/chat/" + dataset.id, {
                          question,
                          filters: filters(),
                          use_llm: useLLM,
                        }),
                      ),
                    )
                  }
                >
                  بررسی پرسش
                </button>
              </section>
              <section>
                <h2>تحلیل تکمیلی</h2>
                <label>
                  نوع تحلیل
                  <select
                    value={advanced}
                    onChange={(e) => setAdvanced(e.target.value)}
                  >
                    <option value="forecast">پیش‌بینی روزانه فروش</option>
                    <option value="cluster">خوشه‌بندی مشتریان</option>
                    <option value="nlp">واژه‌ها و موضوعات بازخورد</option>
                  </select>
                </label>
                {advanced === "forecast" && (
                  <label>
                    تعداد روز پیش‌بینی
                    <input
                      type="number"
                      min="1"
                      max="30"
                      value={horizon}
                      onChange={(e) => setHorizon(Number(e.target.value))}
                    />
                  </label>
                )}
                <button
                  className="mt-4"
                  disabled={busy}
                  onClick={() =>
                    void action(async () =>
                      setResult(
                        await task(
                          (advanced === "nlp"
                            ? "/nlp/"
                            : "/ml/" + advanced + "/") + dataset.id,
                          advanced === "forecast"
                            ? { horizon, missing_days: "error" }
                            : undefined,
                        ),
                      ),
                    )
                  }
                >
                  اجرای تحلیل
                </button>
                <label className="mt-4">
                  سند داخلی برای جست‌وجوی محلی
                  <input
                    type="file"
                    accept=".txt,.md,.pdf,.docx"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file)
                        void action(async () => {
                          const form = new FormData();
                          form.append("file", file);
                          setResult(
                            await task("/rag/documents/" + dataset.id, form),
                          );
                        });
                    }}
                  />
                </label>
              </section>
              <section>
                <h2>سناریوی فرضی فروش</h2>
                <p className="muted">
                  این محاسبه اثر فرض‌های شما را نشان می‌دهد. واکنش مشتری یا
                  آینده بازار را پیش‌بینی نمی‌کند.
                </p>
                <div className="grid">
                  <label>
                    تغییر قیمت، درصد
                    <input
                      type="number"
                      value={priceChange}
                      onChange={(e) => setPriceChange(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    تغییر تعداد فروش، درصد
                    <input
                      type="number"
                      value={volumeChange}
                      onChange={(e) => setVolumeChange(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    نرخ تخفیف فعلی، درصد
                    <input
                      type="number"
                      value={discountRate}
                      onChange={(e) => setDiscountRate(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    تغییر تخفیف، واحد درصد
                    <input
                      type="number"
                      value={discountPoints}
                      onChange={(e) =>
                        setDiscountPoints(Number(e.target.value))
                      }
                    />
                  </label>
                </div>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={scenarioConfirmed}
                    onChange={(e) => setScenarioConfirmed(e.target.checked)}
                  />
                  فرض‌های قیمت، تعداد، تخفیف و ثابت‌بودن هزینه هر واحد را تأیید
                  می‌کنم.
                </label>
                <button
                  disabled={busy || !scenarioConfirmed}
                  onClick={() =>
                    void action(async () =>
                      setResult(
                        await api("/simulation/" + dataset.id, "POST", {
                          price_change: priceChange / 100,
                          volume_change: volumeChange / 100,
                          current_discount_rate: discountRate / 100,
                          discount_change_points: discountPoints / 100,
                          assumptions_confirmed: true,
                        }),
                      ),
                    )
                  }
                >
                  محاسبه سناریو
                </button>
              </section>
            </>
          )}
          {result !== null && (
            <section>
              <h2>نتیجه و جزئیات بررسی</h2>
              <Result value={result} />
            </section>
          )}
        </>
      )}
      <p className="small muted">
        این نسخه برای استفاده محلی یک شرکت طراحی شده است. پیشنهادهای تجاری نیاز
        به بررسی انسانی دارند.
      </p>
    </main>
  );
}
