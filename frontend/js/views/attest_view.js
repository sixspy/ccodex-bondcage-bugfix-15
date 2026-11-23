export const attestViewTemplate = `
<section class="panel">
  <h2>履约核验</h2>
  <p class="hint">对已冻结笼给出通过或违约结论；同一笼代不得改口。通过后可解笼，违约后可罚没。</p>
  <div class="grid-2">
    <div>
      <div class="form-row">
        <div>
          <label>笼</label>
          <select v-model.number="attestForm.cage_id">
            <option :value="0">请选择</option>
            <option v-for="c in frozenCages" :key="c.id" :value="c.id">
              {{ c.cage_code }} · {{ fmt(c.available) }} · 代{{ c.generation }}
            </option>
          </select>
        </div>
        <div>
          <label>结论</label>
          <select v-model="attestForm.outcome">
            <option>通过</option>
            <option>违约</option>
          </select>
        </div>
        <div style="grid-column:1/-1">
          <label>证据摘要</label>
          <textarea v-model="attestForm.evidence" placeholder="验收单号 / 违约说明"></textarea>
        </div>
      </div>
      <div class="actions">
        <button class="ok" @click="doAttest">提交核验</button>
      </div>
    </div>
    <div>
      <table>
        <thead>
          <tr><th>时间</th><th>笼</th><th>结论</th><th>笼代</th><th>核验员</th><th>证据</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in attestations" :key="a.id">
            <td>{{ a.created_at }}</td>
            <td>{{ a.cage_code }}</td>
            <td><span class="badge" :class="a.outcome==='通过'?'pass':'fail'">{{ a.outcome }}</span></td>
            <td>{{ a.attest_gen }}</td>
            <td>{{ a.officer }}</td>
            <td>{{ a.evidence }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
`;
