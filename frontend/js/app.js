import { createApi } from "./api.js";
import { bondsViewTemplate } from "./views/bonds_view.js";
import { cagesViewTemplate } from "./views/cages_view.js";
import { attestViewTemplate } from "./views/attest_view.js";
import { releaseViewTemplate } from "./views/release_view.js";
import { forfeitViewTemplate } from "./views/forfeit_view.js";
import { reconcileViewTemplate } from "./views/reconcile_view.js";
import { auditViewTemplate } from "./views/audit_view.js";
import { stubsViewTemplate } from "./views/stubs_view.js";

const { createApp, ref, computed, onMounted } = Vue;

createApp({
  setup() {
    const token = ref(localStorage.getItem("bondcage_token") || "");
    const user = ref(localStorage.getItem("bondcage_user") || "");
    const username = ref("admin");
    const password = ref("123456");
    const err = ref("");
    const actionErr = ref("");
    const actionOk = ref("");
    const tab = ref(0);
    const nav = [
      "保证金户",
      "入笼冻结",
      "履约核验",
      "解笼拨付",
      "罚没册",
      "对账互证",
      "审计争用",
      "增补拆笼",
    ];

    const bonds = ref([]);
    const cages = ref([]);
    const attestations = ref([]);
    const releases = ref([]);
    const forfeits = ref([]);
    const recon = ref({});
    const partyProof = ref(null);
    const proofParty = ref("P-EAST");
    const audits = ref([]);
    const contention = ref([]);
    const locks = ref([]);
    const dash = ref({});
    const bondDetail = ref(null);
    const cageDetail = ref(null);
    const selectedCage = ref(null);
    const topupJobs = ref([]);
    const splitJobs = ref([]);

    const bondForm = ref({
      party_key: "P-NEW",
      party_name: "新当事方",
      initial_deposit: 100000,
    });
    const depositForm = ref({
      party_key: "P-WEST",
      amount: 20000,
      memo: "追加入金",
    });
    const freezeForm = ref({
      party_key: "P-WEST",
      contract_no: "HT-2026-1201",
      amount: 30000,
      beneficiary: "业主方",
      cage_code: "",
    });
    const attestForm = ref({
      cage_id: 0,
      outcome: "通过",
      evidence: "验收合格",
    });
    const releaseForm = ref({
      cage_id: 0,
      amount: null,
      payee: "",
    });
    const forfeitForm = ref({
      cage_id: 0,
      amount: null,
      reason: "履约违约",
    });
    const topupForm = ref({
      cage_id: 0,
      amount: 10000,
      mode: "同笼扩代",
    });
    const splitForm = ref({
      cage_id: 0,
      left_amount: 10000,
      right_amount: 10000,
      mode: "整笔切分",
    });

    function logout() {
      token.value = "";
      user.value = "";
      localStorage.removeItem("bondcage_token");
      localStorage.removeItem("bondcage_user");
    }

    const api = createApi(
      () => token.value,
      () => logout()
    );

    function fmt(n) {
      const x = Number(n || 0);
      return x.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    }

    function shortStatus(s) {
      if (!s) return "";
      if (s.includes("冻结")) return "冻";
      if (s.includes("通过")) return "通";
      if (s.includes("违约")) return "违";
      if (s.includes("解笼")) return "解";
      if (s.includes("罚没")) return "罚";
      return s.slice(0, 1);
    }

    function statusClass(s) {
      if (!s) return "frozen";
      if (s.includes("通过") || s.includes("解笼")) return "pass";
      if (s.includes("违约") || s.includes("罚没")) return "fail";
      if (s.includes("冻结")) return "frozen";
      return "done";
    }

    const frozenCages = computed(() =>
      cages.value.filter((c) => c.status === "已冻结")
    );
    const passCages = computed(() =>
      cages.value.filter(
        (c) => c.status === "核验通过" || c.status === "部分解笼"
      )
    );
    const failCages = computed(() =>
      cages.value.filter(
        (c) => c.status === "核验违约" || c.status === "部分罚没"
      )
    );

    async function login() {
      err.value = "";
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.value,
          password: password.value,
        }),
      });
      const j = await r.json();
      if (!r.ok) {
        err.value = j.detail || "登录失败";
        return;
      }
      token.value = j.token;
      user.value = j.username;
      localStorage.setItem("bondcage_token", j.token);
      localStorage.setItem("bondcage_user", j.username);
      await refresh();
    }

    function clearFlash() {
      actionErr.value = "";
      actionOk.value = "";
    }

    function flashOk(msg) {
      actionOk.value = msg;
      actionErr.value = "";
    }

    function flashErr(e) {
      actionErr.value = e.message || String(e);
      actionOk.value = "";
    }

    async function refresh() {
      if (!token.value) return;
      clearFlash();
      try {
        const [
          b,
          c,
          a,
          r,
          f,
          d,
          au,
          ct,
          lk,
          tj,
          sj,
        ] = await Promise.all([
          api.bonds(),
          api.cages(),
          api.attestations(),
          api.releases(),
          api.forfeits(),
          api.dashboard(),
          api.audit(),
          api.contention(),
          api.locks(),
          api.topupJobs(),
          api.splitJobs(),
        ]);
        bonds.value = b.items || [];
        cages.value = c.items || [];
        attestations.value = a.items || [];
        releases.value = r.items || [];
        forfeits.value = f.items || [];
        dash.value = d || {};
        audits.value = au.items || [];
        contention.value = ct.items || [];
        locks.value = lk.items || [];
        topupJobs.value = tj.items || [];
        splitJobs.value = sj.items || [];
        if (!attestForm.value.cage_id && frozenCages.value.length) {
          attestForm.value.cage_id = frozenCages.value[0].id;
        }
        if (!releaseForm.value.cage_id && passCages.value.length) {
          releaseForm.value.cage_id = passCages.value[0].id;
        }
        if (!forfeitForm.value.cage_id && failCages.value.length) {
          forfeitForm.value.cage_id = failCages.value[0].id;
        }
        if (!topupForm.value.cage_id && cages.value.length) {
          topupForm.value.cage_id = cages.value[0].id;
        }
        if (!splitForm.value.cage_id && cages.value.length) {
          const cg = cages.value[0];
          splitForm.value.cage_id = cg.id;
          const half = Math.floor(Number(cg.available) / 2);
          splitForm.value.left_amount = half;
          splitForm.value.right_amount = Number(cg.available) - half;
        }
      } catch (e) {
        flashErr(e);
      }
    }

    async function openBond() {
      clearFlash();
      try {
        await api.openBond(bondForm.value);
        flashOk("开户成功");
        await refresh();
      } catch (e) {
        flashErr(e);
      }
    }

    async function deposit() {
      clearFlash();
      try {
        await api.deposit(depositForm.value);
        flashOk("入金成功");
        await refresh();
        await loadBondDetail(depositForm.value.party_key);
      } catch (e) {
        flashErr(e);
      }
    }

    async function loadBondDetail(key) {
      if (!key) return;
      try {
        bondDetail.value = await api.bond(key);
      } catch (e) {
        flashErr(e);
      }
    }

    async function freezeCage() {
      clearFlash();
      try {
        const payload = { ...freezeForm.value };
        if (!payload.cage_code) delete payload.cage_code;
        const row = await api.freeze(payload);
        flashOk(`入笼成功 ${row.cage_code}`);
        await refresh();
        await selectCage(row);
      } catch (e) {
        flashErr(e);
      }
    }

    async function selectCage(c) {
      selectedCage.value = c;
      try {
        cageDetail.value = await api.cage(c.id);
      } catch (e) {
        flashErr(e);
      }
    }

    async function doAttest() {
      clearFlash();
      try {
        if (!attestForm.value.cage_id) throw new Error("请选择笼");
        await api.attest(attestForm.value);
        flashOk("核验已写入");
        await refresh();
      } catch (e) {
        flashErr(e);
      }
    }

    async function doRelease() {
      clearFlash();
      try {
        if (!releaseForm.value.cage_id) throw new Error("请选择笼");
        const payload = { cage_id: releaseForm.value.cage_id };
        if (releaseForm.value.amount) payload.amount = releaseForm.value.amount;
        if (releaseForm.value.payee) payload.payee = releaseForm.value.payee;
        const row = await api.release(payload);
        flashOk(`拨付成功 ${row.release_ref}`);
        await refresh();
      } catch (e) {
        flashErr(e);
      }
    }

    async function doForfeit() {
      clearFlash();
      try {
        if (!forfeitForm.value.cage_id) throw new Error("请选择笼");
        const payload = {
          cage_id: forfeitForm.value.cage_id,
          reason: forfeitForm.value.reason,
        };
        if (forfeitForm.value.amount) payload.amount = forfeitForm.value.amount;
        const row = await api.forfeit(payload);
        flashOk(`罚没成功 ${row.forfeit_ref}`);
        await refresh();
      } catch (e) {
        flashErr(e);
      }
    }

    async function loadReconcile() {
      clearFlash();
      try {
        recon.value = await api.reconcile();
        flashOk("对账已刷新");
      } catch (e) {
        flashErr(e);
      }
    }

    async function loadProof() {
      clearFlash();
      try {
        partyProof.value = await api.proof(proofParty.value);
        flashOk("当事人互证已加载");
      } catch (e) {
        flashErr(e);
      }
    }

    async function doTopupStub() {
      clearFlash();
      try {
        if (!topupForm.value.cage_id) throw new Error("请选择笼");
        const row = await api.topupStub(topupForm.value);
        flashOk(`增补空桩已登记 #${row.job_id}`);
        await refresh();
      } catch (e) {
        flashErr(e);
      }
    }

    async function doSplitStub() {
      clearFlash();
      try {
        if (!splitForm.value.cage_id) throw new Error("请选择笼");
        const row = await api.splitStub(splitForm.value);
        flashOk(`拆笼空桩已登记 #${row.job_id}`);
        await refresh();
      } catch (e) {
        flashErr(e);
      }
    }

    onMounted(async () => {
      if (token.value) await refresh();
    });

    return {
      token,
      user,
      username,
      password,
      err,
      actionErr,
      actionOk,
      tab,
      nav,
      bonds,
      cages,
      attestations,
      releases,
      forfeits,
      recon,
      partyProof,
      proofParty,
      audits,
      contention,
      locks,
      dash,
      bondDetail,
      cageDetail,
      selectedCage,
      topupJobs,
      splitJobs,
      bondForm,
      depositForm,
      freezeForm,
      attestForm,
      releaseForm,
      forfeitForm,
      topupForm,
      splitForm,
      frozenCages,
      passCages,
      failCages,
      login,
      logout,
      refresh,
      fmt,
      shortStatus,
      statusClass,
      openBond,
      deposit,
      loadBondDetail,
      freezeCage,
      selectCage,
      doAttest,
      doRelease,
      doForfeit,
      loadReconcile,
      loadProof,
      doTopupStub,
      doSplitStub,
    };
  },
  template: `
  <div v-if="!token" class="login-shell">
    <div class="login-card">
      <h1>保证金笼</h1>
      <p class="sub">先入笼冻结，履约核验后解笼拨付或罚没，笼代与拨付罚没对账。</p>
      <label>账号</label>
      <input v-model="username"/>
      <label>密码</label>
      <input type="password" v-model="password" @keyup.enter="login"/>
      <button @click="login">进入钢印台</button>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
  </div>
  <div v-else class="shell">
    <header class="topbar">
      <div class="brand">
        保证金笼
        <small>冻结 · 核验 · 解笼/罚没 · 对账</small>
      </div>
      <div class="top-meta">
        <span>{{ user }}</span>
        <button @click="refresh">刷新</button>
        <button @click="logout">退出</button>
      </div>
    </header>
    <div class="dash-strip">
      <div class="dash-chip"><div class="k">账户</div><div class="v">{{ dash.bonds || 0 }}</div></div>
      <div class="dash-chip"><div class="k">笼数</div><div class="v">{{ dash.cages || 0 }}</div></div>
      <div class="dash-chip"><div class="k">冻结可用</div><div class="v">{{ fmt(dash.frozen_available) }}</div></div>
      <div class="dash-chip"><div class="k">已拨付</div><div class="v">{{ fmt(dash.released_total) }}</div></div>
      <div class="dash-chip"><div class="k">已罚没</div><div class="v">{{ fmt(dash.forfeited_total) }}</div></div>
    </div>
    <nav class="nav">
      <button v-for="(n,i) in nav" :key="n" :class="{active: tab===i}" @click="tab=i">{{ n }}</button>
    </nav>
    <div class="action-err" v-if="actionErr">{{ actionErr }}</div>
    <div class="ok-msg" v-if="actionOk">{{ actionOk }}</div>
    <div v-show="tab===0">${bondsViewTemplate}</div>
    <div v-show="tab===1">${cagesViewTemplate}</div>
    <div v-show="tab===2">${attestViewTemplate}</div>
    <div v-show="tab===3">${releaseViewTemplate}</div>
    <div v-show="tab===4">${forfeitViewTemplate}</div>
    <div v-show="tab===5">${reconcileViewTemplate}</div>
    <div v-show="tab===6">${auditViewTemplate}</div>
    <div v-show="tab===7">${stubsViewTemplate}</div>
  </div>
  `,
}).mount("#app");
