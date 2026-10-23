<script setup>
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const API_BASE_URL = import.meta.env.VITE_AUTH_API_URL || "";
const route = useRoute();
const router = useRouter();
const username = ref("");
const password = ref("");
const message = ref("");
const isLoading = ref(false);
const isSignup = computed(() => route.path === "/signup");
const title = computed(() => isSignup.value ? "회원가입" : "로그인");

async function submit() {
  if (isLoading.value) return;
  message.value = "";
  isLoading.value = true;

  try {
    const response = await fetch(`${API_BASE_URL}/api/${isSignup.value ? "signup" : "login"}`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: username.value, password: password.value }),
      credentials: "include",
    });
    const result = await response.json();

    if (!response.ok) {
      message.value = result.error || `요청에 실패했습니다. (${response.status})`;
      return;
    }

    if (isSignup.value) {
      await router.push("/login");
    } else {
      await router.push("/home");
    }
  } catch (error) {
    console.error(error);
    message.value = "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-card">
      <RouterLink class="auth-brand" to="/login">HeartSignal</RouterLink>
      <p class="auth-eyebrow">안전 정보 서비스</p>
      <h1>{{ title }}</h1>
      <p class="auth-description">
        {{ isSignup ? "계정을 만들고 안전 정보를 확인해 보세요." : "계정에 로그인해 안전 정보를 확인하세요." }}
      </p>

      <form class="auth-form" @submit.prevent="submit">
        <label for="username">아이디</label>
        <input
          id="username"
          v-model.trim="username"
          name="username"
          type="text"
          autocomplete="username"
          required
        >

        <label for="password">비밀번호</label>
        <input
          id="password"
          v-model="password"
          name="password"
          type="password"
          :autocomplete="isSignup ? 'new-password' : 'current-password'"
          required
        >

        <p v-if="message" class="form-message" role="alert">{{ message }}</p>
        <button class="primary-button" type="submit" :disabled="isLoading">
          {{ isLoading ? "처리 중..." : title }}
        </button>
      </form>

      <p class="auth-switch">
        <template v-if="isSignup">
          이미 계정이 있으신가요? <RouterLink to="/login">로그인</RouterLink>
        </template>
        <template v-else>
          계정이 없으신가요? <RouterLink to="/signup">회원가입</RouterLink>
        </template>
      </p>
    </section>
  </main>
</template>
